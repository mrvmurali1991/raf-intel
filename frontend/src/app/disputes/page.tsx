"use client";

/**
 * Disputes & Appeals — Kanban-style status board.
 *
 * Columns: open | in_review | appealing | won | lost
 * (`abandoned` is shown in a collapsible section at the bottom)
 *
 * Per-card quick actions:
 *   - Assign        → POST /api/disputes/{id}/assign
 *   - Gather evidence → POST /api/disputes/{id}/gather-evidence
 *   - Draft appeal   → POST /api/disputes/{id}/draft-appeal (modal preview)
 *   - Submit appeal  → POST /api/disputes/{id}/submit-appeal
 *   - Record outcome → POST /api/appeals/{id}/record-outcome (latest appeal)
 *
 * All TailwindCSS via inline styles (matches existing /suspects page style).
 */

import React, { useEffect, useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Gavel,
  TrendingUp,
  DollarSign,
  Clock,
  Users,
  FileText,
  Send,
  CheckCircle2,
  XCircle,
  Sparkles,
  Plus,
  X,
} from "lucide-react";

import {
  listDisputes,
  getDisputeMetrics,
  gatherDisputeEvidence,
  draftAppeal,
  submitAppeal,
  recordAppealOutcome,
  assignDispute,
  createDispute,
  getDispute,
  type Dispute,
  type DisputeStatus,
} from "@/lib/api";
import {
  StatCard,
  PageHeader,
} from "@/components/healthcare-ui";
import { useToast } from "@/components/Toast";

/* ------------------------------------------------------------------ */
/*  Tokens (mirrors the existing /suspects palette)                    */
/* ------------------------------------------------------------------ */

const T = {
  white: "#FFFFFF",
  slate50: "#F8FAFC",
  slate100: "#F1F5F9",
  slate200: "#E2E8F0",
  slate300: "#CBD5E1",
  slate400: "#94A3B8",
  slate500: "#64748B",
  slate600: "#475569",
  slate700: "#334155",
  slate800: "#1E293B",
  blue50: "#EFF6FF",
  blue500: "#3B82F6",
  blue600: "#2563EB",
  blue700: "#1D4ED8",
  emerald50: "#ECFDF5",
  emerald500: "#10B981",
  emerald600: "#059669",
  amber50: "#FFFBEB",
  amber500: "#F59E0B",
  amber600: "#D97706",
  red50: "#FEF2F2",
  red500: "#EF4444",
  red600: "#DC2626",
  purple50: "#FAF5FF",
  purple500: "#A855F7",
  purple600: "#9333EA",
};

const COLUMNS: { status: DisputeStatus; label: string; accent: string; bg: string }[] = [
  { status: "open",       label: "Open",        accent: T.blue600,    bg: T.blue50 },
  { status: "in_review",  label: "In Review",   accent: T.amber600,   bg: T.amber50 },
  { status: "appealing",  label: "Appealing",   accent: T.purple600,  bg: T.purple50 },
  { status: "won",        label: "Won",         accent: T.emerald600, bg: T.emerald50 },
  { status: "lost",       label: "Lost",        accent: T.red600,     bg: T.red50 },
];

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export default function DisputesPage() {
  const qc = useQueryClient();
  const toast = useToast();

  const [selected, setSelected] = useState<Dispute | null>(null);
  const [draftModal, setDraftModal] = useState<{ disputeId: number; text: string } | null>(null);
  const [outcomeModal, setOutcomeModal] = useState<{ appealId: number; disputeId: number } | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  // Allow the patient detail page to deep-link into a "new dispute" flow
  // with patient_id + measurement_year pre-populated. Read from the URL
  // once on mount so refreshing this page doesn't keep re-opening the
  // dialog. UX: hand-off coder → disputes board in one click.
  const [deepLinkPid, setDeepLinkPid] = useState<string>("");
  const [deepLinkMy, setDeepLinkMy] = useState<string>("");
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("new") === "1") {
      setDeepLinkPid(params.get("patient_id") || "");
      setDeepLinkMy(params.get("measurement_year") || "");
      setShowCreate(true);
    }
  }, []);

  /* ---------------- Data ---------------- */

  const { data: disputeData, isLoading: loadingDisputes } = useQuery({
    queryKey: ["disputes", "all"],
    queryFn: () => listDisputes({ limit: 500 }),
  });

  const { data: metrics } = useQuery({
    queryKey: ["disputes", "metrics"],
    queryFn: () => getDisputeMetrics(),
  });

  const allDisputes: Dispute[] = disputeData?.disputes ?? [];

  const grouped = useMemo(() => {
    const map: Record<DisputeStatus, Dispute[]> = {
      open: [], in_review: [], appealing: [], won: [], lost: [], abandoned: [],
    };
    for (const d of allDisputes) map[d.status]?.push(d);
    return map;
  }, [allDisputes]);

  /* ---------------- Mutations ---------------- */

  const invalidate = () => qc.invalidateQueries({ queryKey: ["disputes"] });

  const gatherMut = useMutation({
    mutationFn: (id: number) => gatherDisputeEvidence(id),
    onSuccess: (res) => {
      toast.success("Evidence gathered", `Pulled ${res.count} MEAT evidence rows.`);
      invalidate();
      if (selected?.id === res.dispute_id) refreshSelected(res.dispute_id);
    },
    onError: () => toast.error("Error", "Failed to gather evidence."),
  });

  const draftMut = useMutation({
    mutationFn: (id: number) => draftAppeal(id, 1),
    onSuccess: (res) => setDraftModal({ disputeId: res.dispute_id, text: res.draft_text }),
    onError: (err: any) =>
      toast.error("Cannot draft appeal", err?.response?.data?.detail ?? "Try gathering evidence first."),
  });

  const submitMut = useMutation({
    mutationFn: (vars: { id: number; text: string }) =>
      submitAppeal(vars.id, {
        appeal_round: 1,
        appeal_letter_text: vars.text,
        appeal_letter_model: "gemini-2.5-pro",
        submitted_by: "frontend_user",
      }),
    onSuccess: () => {
      toast.success("Appeal submitted", "Dispute moved to 'appealing'.");
      setDraftModal(null);
      invalidate();
    },
    onError: () => toast.error("Error", "Failed to submit appeal."),
  });

  const assignMut = useMutation({
    mutationFn: (vars: { id: number; user: string }) => assignDispute(vars.id, vars.user),
    onSuccess: () => { toast.success("Assigned", "Owner updated."); invalidate(); },
    onError: () => toast.error("Error", "Failed to assign."),
  });

  const createMut = useMutation({
    mutationFn: (payload: any) => createDispute(payload),
    onSuccess: () => { toast.success("Dispute created", ""); setShowCreate(false); invalidate(); },
    onError: (err: any) => toast.error("Error", err?.response?.data?.detail ?? "Failed."),
  });

  const outcomeMut = useMutation({
    mutationFn: (vars: { appealId: number; outcome: any; amount: number }) =>
      recordAppealOutcome(vars.appealId, {
        outcome: vars.outcome,
        recovered_amount: vars.amount,
      }),
    onSuccess: () => { toast.success("Outcome recorded", ""); setOutcomeModal(null); invalidate(); },
    onError: () => toast.error("Error", "Failed to record outcome."),
  });

  function refreshSelected(id: number) {
    getDispute(id).then(setSelected).catch(() => {});
  }

  /* ---------------- Render ---------------- */

  return (
    <div style={{ maxWidth: 1600, margin: "0 auto", padding: "24px 16px", fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" }}>
      <PageHeader
        title="Disputes & Appeals"
        subtitle="Track CMS / payer denials, gather MEAT evidence, draft appeals, and recover revenue."
        icon={<Gavel size={22} />}
        actions={
          <button
            onClick={() => setShowCreate(true)}
            style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              background: T.blue600, color: T.white, border: "none",
              padding: "8px 14px", borderRadius: 8, fontSize: 13, fontWeight: 600,
              cursor: "pointer",
            }}
          >
            <Plus size={14} /> New Dispute
          </button>
        }
      />

      {/* ── Metrics Strip ───────────────────────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 16, marginBottom: 24 }}>
        <StatCard
          label="Win Rate"
          value={metrics ? `${(metrics.win_rate * 100).toFixed(1)}%` : "--"}
          icon={<TrendingUp size={18} />}
          color={T.emerald600}
        />
        <StatCard
          label="$ Recovered"
          value={metrics ? formatMoney(metrics.money_recovered) : "--"}
          icon={<DollarSign size={18} />}
          color={T.blue600}
        />
        <StatCard
          label="$ At Risk (Open)"
          value={metrics ? formatMoney(metrics.money_at_risk) : "--"}
          icon={<DollarSign size={18} />}
          color={T.amber600}
        />
        <StatCard
          label="Avg Cycle (days)"
          value={metrics ? metrics.avg_cycle_time_days.toFixed(1) : "--"}
          icon={<Clock size={18} />}
          color={T.purple600}
        />
      </div>

      {/* ── Kanban ──────────────────────────────────────────────── */}
      <div style={{ width: "100%", maxWidth: "100%", overflowX: "auto", WebkitOverflowScrolling: "touch", marginBottom: 0 }}>
      <div style={{ display: "flex", gap: 10, minWidth: 1100 }}>
        {COLUMNS.map((col) => (
          <KanbanColumn
            key={col.status}
            label={col.label}
            accent={col.accent}
            bg={col.bg}
            disputes={grouped[col.status] ?? []}
            loading={loadingDisputes}
            onSelect={(d) => { setSelected(d); refreshSelected(d.id); }}
            onGather={(id) => gatherMut.mutate(id)}
            onDraft={(id) => draftMut.mutate(id)}
            onAssign={(id) => {
              const u = window.prompt("Assign to (username):");
              if (u) assignMut.mutate({ id, user: u });
            }}
            onRecordOutcome={(d) => {
              const lastAppeal = d.appeals?.[d.appeals.length - 1];
              if (!lastAppeal) {
                toast.error("No appeal", "Submit an appeal first.");
                return;
              }
              setOutcomeModal({ appealId: lastAppeal.id, disputeId: d.id });
            }}
          />
        ))}
      </div>
      </div>

      {/* Abandoned section (collapsed) */}
      {grouped.abandoned.length > 0 && (
        <details style={{ marginTop: 24, background: T.white, border: `1px solid ${T.slate200}`, borderRadius: 10, padding: 12 }}>
          <summary style={{ cursor: "pointer", fontWeight: 600, color: T.slate600, fontSize: 13 }}>
            Abandoned ({grouped.abandoned.length})
          </summary>
          <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
            {grouped.abandoned.map((d) => <CardLite key={d.id} d={d} onClick={() => { setSelected(d); refreshSelected(d.id); }} />)}
          </div>
        </details>
      )}

      {/* ── Detail drawer ───────────────────────────────────────── */}
      {selected && (
        <DetailDrawer dispute={selected} onClose={() => setSelected(null)} />
      )}

      {/* ── Draft preview modal ─────────────────────────────────── */}
      {draftModal && (
        <Modal
          title="Appeal letter draft"
          onClose={() => setDraftModal(null)}
          actions={
            <>
              <button
                onClick={() => setDraftModal(null)}
                style={btnSecondary()}
              >Cancel</button>
              <button
                onClick={() => submitMut.mutate({ id: draftModal.disputeId, text: draftModal.text })}
                style={btnPrimary()}
                disabled={submitMut.isPending}
              >
                <Send size={14} /> {submitMut.isPending ? "Submitting…" : "Submit Appeal"}
              </button>
            </>
          }
        >
          <textarea
            value={draftModal.text}
            onChange={(e) => setDraftModal({ ...draftModal, text: e.target.value })}
            rows={20}
            style={{
              width: "100%", padding: 12, border: `1px solid ${T.slate200}`,
              borderRadius: 6, fontFamily: "monospace", fontSize: 12, lineHeight: 1.5,
            }}
          />
          <p style={{ fontSize: 12, color: T.slate500, marginTop: 8 }}>
            <Sparkles size={12} style={{ display: "inline" }} /> AI-drafted; edit before submission.
            Letter cites only the evidence attached to this dispute.
          </p>
        </Modal>
      )}

      {/* ── Outcome modal ───────────────────────────────────────── */}
      {outcomeModal && (
        <OutcomeModal
          onClose={() => setOutcomeModal(null)}
          onSubmit={(outcome, amount) =>
            outcomeMut.mutate({ appealId: outcomeModal.appealId, outcome, amount })
          }
          submitting={outcomeMut.isPending}
        />
      )}

      {/* ── Create modal ────────────────────────────────────────── */}
      {showCreate && (
        <CreateModal
          onClose={() => setShowCreate(false)}
          onSubmit={(payload) => createMut.mutate(payload)}
          submitting={createMut.isPending}
          initialPatientId={deepLinkPid}
          initialMeasurementYear={deepLinkMy}
        />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Kanban column                                                      */
/* ------------------------------------------------------------------ */

function KanbanColumn(props: {
  label: string;
  accent: string;
  bg: string;
  disputes: Dispute[];
  loading: boolean;
  onSelect: (d: Dispute) => void;
  onGather: (id: number) => void;
  onDraft: (id: number) => void;
  onAssign: (id: number) => void;
  onRecordOutcome: (d: Dispute) => void;
}) {
  return (
    <div style={{ background: T.slate50, borderRadius: 10, padding: 10, minHeight: 400, flex: "1 0 200px" }}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 10, padding: "0 4px",
      }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: props.accent, textTransform: "uppercase" }}>
          {props.label}
        </span>
        <span style={{
          background: props.bg, color: props.accent, fontSize: 11, fontWeight: 700,
          padding: "2px 8px", borderRadius: 999,
        }}>
          {props.disputes.length}
        </span>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {props.loading && Array.from({ length: 3 }).map((_, i) => (
          <div key={i} style={{ height: 110, background: T.slate100, borderRadius: 8, animation: "pulse 1.5s infinite" }} />
        ))}

        {!props.loading && props.disputes.length === 0 && (
          <div style={{ fontSize: 12, color: T.slate400, textAlign: "center", padding: 24 }}>
            No disputes
          </div>
        )}

        {!props.loading && props.disputes.map((d) => (
          <DisputeCard
            key={d.id}
            d={d}
            accent={props.accent}
            onClick={() => props.onSelect(d)}
            onGather={() => props.onGather(d.id)}
            onDraft={() => props.onDraft(d.id)}
            onAssign={() => props.onAssign(d.id)}
            onRecordOutcome={() => props.onRecordOutcome(d)}
          />
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Dispute card                                                       */
/* ------------------------------------------------------------------ */

function DisputeCard(props: {
  d: Dispute;
  accent: string;
  onClick: () => void;
  onGather: () => void;
  onDraft: () => void;
  onAssign: () => void;
  onRecordOutcome: () => void;
}) {
  const { d } = props;
  return (
    <div
      onClick={props.onClick}
      style={{
        background: T.white, border: `1px solid ${T.slate200}`,
        borderRadius: 8, padding: 10, cursor: "pointer",
        boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
        borderLeft: `3px solid ${props.accent}`,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
        <span style={{ fontSize: 11, color: T.slate500, fontWeight: 600 }}>#{d.id} · pid {d.patient_id}</span>
        <span style={{ fontSize: 10, color: T.slate400, textTransform: "uppercase" }}>{d.disputed_by}</span>
      </div>

      <div style={{ display: "flex", gap: 6, marginTop: 6, alignItems: "center" }}>
        <span style={{
          fontSize: 11, fontFamily: "monospace", fontWeight: 700,
          background: T.slate100, padding: "2px 6px", borderRadius: 4,
        }}>
          HCC {d.hcc_code}
        </span>
        <span style={{
          fontSize: 11, fontFamily: "monospace",
          background: T.slate100, padding: "2px 6px", borderRadius: 4,
        }}>
          {d.icd10}
        </span>
      </div>

      {d.denial_reason_text && (
        <div style={{
          fontSize: 11, color: T.slate600, marginTop: 8,
          overflow: "hidden", textOverflow: "ellipsis",
          display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
        }}>
          {d.denial_reason_text}
        </div>
      )}

      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        marginTop: 8, fontSize: 11,
      }}>
        <span style={{ color: T.amber600, fontWeight: 700 }}>
          {formatMoney(Number(d.financial_impact) || 0)}
        </span>
        <span style={{ color: T.slate400 }}>
          {d.assigned_to ?? "Unassigned"}
        </span>
      </div>

      {/* Quick actions */}
      <div
        style={{ display: "flex", gap: 4, marginTop: 8, flexWrap: "wrap" }}
        onClick={(e) => e.stopPropagation()}
      >
        {(d.status === "open" || d.status === "in_review") && (
          <>
            <ActionPill label="Gather" icon={<FileText size={11} />} onClick={props.onGather} />
            <ActionPill label="Draft" icon={<Sparkles size={11} />} onClick={props.onDraft} />
            <ActionPill label="Assign" icon={<Users size={11} />} onClick={props.onAssign} />
          </>
        )}
        {d.status === "appealing" && (
          <ActionPill label="Outcome" icon={<CheckCircle2 size={11} />} onClick={props.onRecordOutcome} />
        )}
      </div>
    </div>
  );
}

function CardLite({ d, onClick }: { d: Dispute; onClick: () => void }) {
  return (
    <div
      onClick={onClick}
      style={{
        background: T.slate50, padding: "8px 12px", borderRadius: 6, cursor: "pointer",
        fontSize: 12, color: T.slate600, display: "flex", justifyContent: "space-between",
      }}
    >
      <span>#{d.id} · pid {d.patient_id} · HCC {d.hcc_code} ({d.icd10})</span>
      <span>{formatMoney(Number(d.financial_impact) || 0)}</span>
    </div>
  );
}

function ActionPill(props: { label: string; icon: React.ReactNode; onClick: () => void }) {
  return (
    <button
      onClick={props.onClick}
      style={{
        display: "inline-flex", alignItems: "center", gap: 3,
        background: T.slate100, border: `1px solid ${T.slate200}`,
        color: T.slate700, fontSize: 10, fontWeight: 600,
        padding: "3px 7px", borderRadius: 4, cursor: "pointer",
      }}
    >
      {props.icon} {props.label}
    </button>
  );
}

/* ------------------------------------------------------------------ */
/*  Detail drawer                                                      */
/* ------------------------------------------------------------------ */

function DetailDrawer({ dispute, onClose }: { dispute: Dispute; onClose: () => void }) {
  return (
    <div style={{
      position: "fixed", top: 0, right: 0, bottom: 0, width: 480,
      background: T.white, borderLeft: `1px solid ${T.slate200}`,
      boxShadow: "-8px 0 24px rgba(0,0,0,0.1)", overflowY: "auto", zIndex: 100, padding: 24,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
        <h2 style={{ fontSize: 18, fontWeight: 700, color: T.slate800 }}>
          Dispute #{dispute.id}
        </h2>
        <button onClick={onClose} style={{ border: "none", background: "transparent", cursor: "pointer" }}>
          <X size={18} color={T.slate500} />
        </button>
      </div>

      <DetailRow label="Patient ID" value={String(dispute.patient_id)} />
      <DetailRow label="HCC / ICD-10" value={`HCC ${dispute.hcc_code} · ${dispute.icd10}`} />
      <DetailRow label="Disputed by" value={`${dispute.disputed_by}${dispute.payer_name ? " (" + dispute.payer_name + ")" : ""}`} />
      <DetailRow label="Status" value={dispute.status} />
      <DetailRow label="Financial impact" value={formatMoney(Number(dispute.financial_impact) || 0)} />
      <DetailRow label="Denial received" value={dispute.denial_received_at} />
      <DetailRow label="Reason" value={dispute.denial_reason_text || dispute.denial_reason_code || "—"} />
      <DetailRow label="Assigned to" value={dispute.assigned_to ?? "Unassigned"} />

      <h3 style={{ marginTop: 20, fontSize: 13, fontWeight: 700, color: T.slate700 }}>
        Evidence ({dispute.evidence?.length ?? 0})
      </h3>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
        {(dispute.evidence ?? []).map((e) => (
          <div key={e.id} style={{ background: T.slate50, padding: 10, borderRadius: 6, fontSize: 12, color: T.slate700 }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
              <span style={{ fontWeight: 600 }}>{e.evidence_type} · {e.encounter_date ?? "—"}</span>
              <span style={{ fontFamily: "monospace", color: T.emerald600 }}>{e.meat_components ?? "—"}</span>
            </div>
            <div style={{ whiteSpace: "pre-wrap", fontSize: 11, color: T.slate600 }}>
              {e.snippet_text?.slice(0, 400) ?? ""}
            </div>
          </div>
        ))}
      </div>

      <h3 style={{ marginTop: 20, fontSize: 13, fontWeight: 700, color: T.slate700 }}>
        Appeals ({dispute.appeals?.length ?? 0})
      </h3>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
        {(dispute.appeals ?? []).map((a) => (
          <div key={a.id} style={{ background: T.purple50, padding: 10, borderRadius: 6, fontSize: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ fontWeight: 600 }}>Round {a.appeal_round}</span>
              <span style={{
                background: outcomeColor(a.outcome).bg, color: outcomeColor(a.outcome).fg,
                padding: "2px 6px", borderRadius: 4, fontSize: 10, fontWeight: 700,
              }}>
                {a.outcome.toUpperCase()}
              </span>
            </div>
            <div style={{ fontSize: 11, color: T.slate600, marginTop: 4 }}>
              Submitted: {a.submitted_at ?? "—"} · Recovered: {formatMoney(Number(a.monetary_recovered) || 0)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", fontSize: 13, borderBottom: `1px solid ${T.slate100}` }}>
      <span style={{ color: T.slate500 }}>{label}</span>
      <span style={{ color: T.slate800, fontWeight: 500 }}>{value}</span>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Modals                                                             */
/* ------------------------------------------------------------------ */

function Modal(props: { title: string; children: React.ReactNode; actions: React.ReactNode; onClose: () => void }) {
  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(15,23,42,0.6)",
      display: "flex", alignItems: "center", justifyContent: "center", zIndex: 200,
    }}>
      <div style={{
        background: T.white, borderRadius: 12, width: 720, maxWidth: "95vw",
        maxHeight: "90vh", display: "flex", flexDirection: "column",
      }}>
        <div style={{ padding: "16px 20px", borderBottom: `1px solid ${T.slate200}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h3 style={{ fontSize: 16, fontWeight: 700, color: T.slate800 }}>{props.title}</h3>
          <button onClick={props.onClose} style={{ border: "none", background: "transparent", cursor: "pointer" }}>
            <X size={18} color={T.slate500} />
          </button>
        </div>
        <div style={{ padding: 20, flex: 1, overflowY: "auto" }}>{props.children}</div>
        <div style={{ padding: "12px 20px", borderTop: `1px solid ${T.slate200}`, display: "flex", justifyContent: "flex-end", gap: 8 }}>
          {props.actions}
        </div>
      </div>
    </div>
  );
}

function OutcomeModal(props: {
  onClose: () => void;
  onSubmit: (outcome: any, amount: number) => void;
  submitting: boolean;
}) {
  const [outcome, setOutcome] = useState<"overturned" | "upheld" | "partial" | "withdrawn">("overturned");
  const [amount, setAmount] = useState("");
  return (
    <Modal
      title="Record appeal outcome"
      onClose={props.onClose}
      actions={
        <>
          <button onClick={props.onClose} style={btnSecondary()}>Cancel</button>
          <button
            disabled={props.submitting}
            onClick={() => props.onSubmit(outcome, parseFloat(amount) || 0)}
            style={btnPrimary()}
          >
            {props.submitting ? "Saving…" : "Record"}
          </button>
        </>
      }
    >
      <label style={lbl()}>Outcome</label>
      <select value={outcome} onChange={(e) => setOutcome(e.target.value as any)} style={inp()}>
        <option value="overturned">Overturned (won)</option>
        <option value="partial">Partial (won)</option>
        <option value="upheld">Upheld (lost)</option>
        <option value="withdrawn">Withdrawn (abandoned)</option>
      </select>

      <label style={lbl()}>Recovered amount ($)</label>
      <input
        type="number" step="0.01" value={amount}
        onChange={(e) => setAmount(e.target.value)} style={inp()}
        placeholder="0.00"
      />
    </Modal>
  );
}

function CreateModal(props: {
  onClose: () => void;
  onSubmit: (payload: any) => void;
  submitting: boolean;
  /** Optional pre-fill from a deep-link (patient-detail "File Dispute"
   *  menu item) so the coder lands inside a partially-populated form
   *  instead of an empty one. HCC review round-N+1 / Cotiviti hand-off. */
  initialPatientId?: string;
  initialMeasurementYear?: string;
}) {
  const [form, setForm] = useState({
    patient_id: props.initialPatientId ?? "",
    hcc_code: "", icd10: "", disputed_by: "cms",
    payer_name: "", denial_reason_text: "", financial_impact: "",
    denial_received_at: new Date().toISOString().slice(0, 10),
    measurement_year: props.initialMeasurementYear ?? "",
  });
  const set = (k: keyof typeof form, v: string) => setForm({ ...form, [k]: v });

  return (
    <Modal
      title="Create new dispute"
      onClose={props.onClose}
      actions={
        <>
          <button onClick={props.onClose} style={btnSecondary()}>Cancel</button>
          <button
            disabled={props.submitting}
            onClick={() => props.onSubmit({
              patient_id: parseInt(form.patient_id, 10),
              hcc_code: parseInt(form.hcc_code, 10),
              icd10: form.icd10,
              disputed_by: form.disputed_by,
              payer_name: form.payer_name || undefined,
              denial_reason_text: form.denial_reason_text || undefined,
              financial_impact: parseFloat(form.financial_impact) || 0,
              denial_received_at: form.denial_received_at,
            })}
            style={btnPrimary()}
          >
            {props.submitting ? "Saving…" : "Create"}
          </button>
        </>
      }
    >
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div><label style={lbl()}>Patient ID</label><input value={form.patient_id} onChange={(e) => set("patient_id", e.target.value)} style={inp()} /></div>
        <div><label style={lbl()}>HCC code</label><input value={form.hcc_code} onChange={(e) => set("hcc_code", e.target.value)} style={inp()} /></div>
        <div><label style={lbl()}>ICD-10</label><input value={form.icd10} onChange={(e) => set("icd10", e.target.value)} style={inp()} /></div>
        <div><label style={lbl()}>Disputed by</label>
          <select value={form.disputed_by} onChange={(e) => set("disputed_by", e.target.value)} style={inp()}>
            <option value="cms">CMS</option>
            <option value="payer">Payer</option>
            <option value="internal_audit">Internal audit</option>
          </select>
        </div>
        <div><label style={lbl()}>Payer name</label><input value={form.payer_name} onChange={(e) => set("payer_name", e.target.value)} style={inp()} /></div>
        <div><label style={lbl()}>$ at risk</label><input type="number" value={form.financial_impact} onChange={(e) => set("financial_impact", e.target.value)} style={inp()} /></div>
        <div style={{ gridColumn: "1 / -1" }}>
          <label style={lbl()}>Denial reason</label>
          <textarea value={form.denial_reason_text} onChange={(e) => set("denial_reason_text", e.target.value)} style={{ ...inp(), height: 60 }} />
        </div>
        <div><label style={lbl()}>Received date</label><input type="date" value={form.denial_received_at} onChange={(e) => set("denial_received_at", e.target.value)} style={inp()} /></div>
      </div>
    </Modal>
  );
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatMoney(n: number): string {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

function outcomeColor(o: string): { bg: string; fg: string } {
  if (o === "overturned" || o === "partial") return { bg: T.emerald50, fg: T.emerald600 };
  if (o === "upheld") return { bg: T.red50, fg: T.red600 };
  if (o === "withdrawn") return { bg: T.slate100, fg: T.slate500 };
  return { bg: T.amber50, fg: T.amber600 };
}

function btnPrimary(): React.CSSProperties {
  return {
    display: "inline-flex", alignItems: "center", gap: 6,
    background: T.blue600, color: T.white, border: "none",
    padding: "8px 16px", borderRadius: 6, fontSize: 13, fontWeight: 600,
    cursor: "pointer",
  };
}

function btnSecondary(): React.CSSProperties {
  return {
    background: T.white, color: T.slate600, border: `1px solid ${T.slate200}`,
    padding: "8px 14px", borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: "pointer",
  };
}

function lbl(): React.CSSProperties {
  return { display: "block", fontSize: 12, fontWeight: 600, color: T.slate600, marginBottom: 4, marginTop: 8 };
}

function inp(): React.CSSProperties {
  return {
    width: "100%", padding: "8px 10px", border: `1px solid ${T.slate200}`,
    borderRadius: 6, fontSize: 13, color: T.slate800, background: T.white,
  };
}
