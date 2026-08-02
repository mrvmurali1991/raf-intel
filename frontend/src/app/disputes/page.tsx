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
  PageHeader,
} from "@/components/healthcare-ui";
import { MetricCard } from "@/components/ui/metric-card";
import { useToast } from "@/components/Toast";
import { humanizeEvidence } from "@/lib/evidence-labels";

/* ------------------------------------------------------------------ */
/*  Column config with Tailwind class tokens                           */
/* ------------------------------------------------------------------ */

const COLUMNS: {
  status: DisputeStatus;
  label: string;
  accentText: string;
  accentBg: string;
  borderColor: string;
}[] = [
  { status: "open",       label: "Open",        accentText: "text-blue-600 dark:text-blue-400",    accentBg: "bg-blue-50 dark:bg-blue-950",       borderColor: "border-l-blue-600" },
  { status: "in_review",  label: "In Review",   accentText: "text-amber-600 dark:text-amber-400",  accentBg: "bg-amber-50 dark:bg-amber-950",     borderColor: "border-l-amber-600" },
  { status: "appealing",  label: "Appealing",   accentText: "text-purple-600 dark:text-purple-400", accentBg: "bg-purple-50 dark:bg-purple-950",  borderColor: "border-l-purple-600" },
  { status: "won",        label: "Won",         accentText: "text-emerald-600 dark:text-emerald-400", accentBg: "bg-emerald-50 dark:bg-emerald-950", borderColor: "border-l-emerald-600" },
  { status: "lost",       label: "Lost",        accentText: "text-red-600 dark:text-red-400",      accentBg: "bg-red-50 dark:bg-red-950",         borderColor: "border-l-red-600" },
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
    <div className="mx-auto px-4 py-6" style={{ maxWidth: 1600 }}>
      <PageHeader
        title="Disputes & Appeals"
        subtitle="Track CMS / payer denials, gather MEAT evidence, draft appeals, and recover revenue."
        icon={<Gavel size={22} />}
        actions={
          <button
            onClick={() => setShowCreate(true)}
            className="inline-flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 text-white border-none px-3.5 py-2 rounded-lg text-[13px] font-semibold cursor-pointer"
          >
            <Plus size={14} /> New Dispute
          </button>
        }
      />

      {/* ── Metrics Strip ───────────────────────────────────────── */}
      <div className="grid gap-4 mb-6" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))" }}>
        <MetricCard
          label="Win Rate"
          value={metrics ? `${(metrics.win_rate * 100).toFixed(1)}%` : "--"}
          icon={<TrendingUp size={18} />}
          intent="success"
        />
        <MetricCard
          label="$ Recovered"
          value={metrics ? formatMoney(metrics.money_recovered) : "--"}
          icon={<DollarSign size={18} />}
        />
        <MetricCard
          label="$ At Risk (Open)"
          value={metrics ? formatMoney(metrics.money_at_risk) : "--"}
          icon={<DollarSign size={18} />}
          intent="warning"
        />
        <MetricCard
          label="Avg Cycle (days)"
          value={metrics ? metrics.avg_cycle_time_days.toFixed(1) : "--"}
          icon={<Clock size={18} />}
        />
      </div>

      {/* ── Kanban ──────────────────────────────────────────────── */}
      <div className="w-full max-w-full overflow-x-auto" style={{ WebkitOverflowScrolling: "touch" }}>
      <div className="flex gap-2.5" style={{ minWidth: 1100 }}>
        {COLUMNS.map((col) => (
          <KanbanColumn
            key={col.status}
            label={col.label}
            accentText={col.accentText}
            accentBg={col.accentBg}
            borderColor={col.borderColor}
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
        <details className="mt-6 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-[10px] p-3">
          <summary className="cursor-pointer font-semibold text-slate-600 dark:text-slate-300 text-[13px]">
            Abandoned ({grouped.abandoned.length})
          </summary>
          <div className="mt-2 flex flex-col gap-1.5">
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
                className={BTN_SECONDARY}
              >Cancel</button>
              <button
                onClick={() => submitMut.mutate({ id: draftModal.disputeId, text: draftModal.text })}
                className={BTN_PRIMARY}
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
            className="w-full p-3 border border-slate-200 dark:border-slate-700 rounded-md font-mono text-xs leading-relaxed bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-100"
          />
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
            <Sparkles size={12} className="inline" /> AI-drafted; edit before submission.
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
  accentText: string;
  accentBg: string;
  borderColor: string;
  disputes: Dispute[];
  loading: boolean;
  onSelect: (d: Dispute) => void;
  onGather: (id: number) => void;
  onDraft: (id: number) => void;
  onAssign: (id: number) => void;
  onRecordOutcome: (d: Dispute) => void;
}) {
  return (
    <div className="bg-slate-50 dark:bg-slate-800/50 rounded-[10px] p-2.5" style={{ minHeight: 400, flex: "1 0 200px" }}>
      <div className="flex items-center justify-between mb-2.5 px-1">
        <span className={`text-xs font-bold uppercase ${props.accentText}`}>
          {props.label}
        </span>
        <span className={`${props.accentBg} ${props.accentText} text-[11px] font-bold px-2 py-0.5 rounded-full`}>
          {props.disputes.length}
        </span>
      </div>

      <div className="flex flex-col gap-2">
        {props.loading && Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-[110px] bg-slate-100 dark:bg-slate-700 rounded-lg animate-pulse" />
        ))}

        {!props.loading && props.disputes.length === 0 && (
          <div className="text-xs text-slate-500 dark:text-slate-400 text-center p-6">
            No disputes
          </div>
        )}

        {!props.loading && props.disputes.map((d) => (
          <DisputeCard
            key={d.id}
            d={d}
            accentText={props.accentText}
            borderColor={props.borderColor}
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
  accentText: string;
  borderColor: string;
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
      className={`bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg p-2.5 cursor-pointer shadow-sm border-l-[3px] ${props.borderColor}`}
    >
      <div className="flex justify-between items-start">
        <span className="text-[11px] text-slate-500 dark:text-slate-400 font-semibold">#{d.id} · pid {d.patient_id}</span>
        <span className="text-[10px] text-slate-500 dark:text-slate-400 uppercase">{d.disputed_by}</span>
      </div>

      <div className="flex gap-1.5 mt-1.5 items-center">
        <span className="text-[11px] font-mono font-bold bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-200 px-1.5 py-0.5 rounded">
          HCC {d.hcc_code}
        </span>
        <span className="text-[11px] font-mono bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-200 px-1.5 py-0.5 rounded">
          {d.icd10}
        </span>
      </div>

      {d.denial_reason_text && (
        <div className="text-[11px] text-slate-600 dark:text-slate-300 mt-2 overflow-hidden text-ellipsis line-clamp-2">
          {d.denial_reason_text}
        </div>
      )}

      <div className="flex justify-between items-center mt-2 text-[11px]">
        <span className="text-amber-600 dark:text-amber-400 font-bold">
          {formatMoney(Number(d.financial_impact) || 0)}
        </span>
        <span className="text-slate-500 dark:text-slate-400">
          {d.assigned_to ?? "Unassigned"}
        </span>
      </div>

      {/* Quick actions */}
      <div
        className="flex gap-1 mt-2 flex-wrap"
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
      className="bg-slate-50 dark:bg-slate-800 px-3 py-2 rounded-md cursor-pointer text-xs text-slate-600 dark:text-slate-300 flex justify-between"
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
      className="inline-flex items-center gap-0.5 bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-200 text-[10px] font-semibold px-[7px] py-[3px] rounded cursor-pointer hover:bg-slate-200 dark:hover:bg-slate-700"
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
    <div className="fixed top-0 right-0 bottom-0 w-[480px] bg-white dark:bg-slate-900 border-l border-slate-200 dark:border-slate-700 shadow-[-8px_0_24px_rgba(0,0,0,0.1)] overflow-y-auto z-[100] p-6">
      <div className="flex justify-between mb-4">
        <h2 className="text-lg font-bold text-slate-800 dark:text-slate-100">
          Dispute #{dispute.id}
        </h2>
        <button onClick={onClose} aria-label="Close" className="border-none bg-transparent cursor-pointer text-slate-500 dark:text-slate-400">
          <X size={18} />
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

      <h3 className="mt-5 text-[13px] font-bold text-slate-700 dark:text-slate-200">
        Evidence ({dispute.evidence?.length ?? 0})
      </h3>
      <div className="flex flex-col gap-2 mt-2">
        {(dispute.evidence ?? []).map((e) => (
          <div key={e.id} className="bg-slate-50 dark:bg-slate-800 p-2.5 rounded-md text-xs text-slate-700 dark:text-slate-200">
            <div className="flex justify-between mb-1">
              <span className="font-semibold">{humanizeEvidence(e.evidence_type)} · {e.encounter_date ?? "—"}</span>
              <span className="font-mono text-emerald-600 dark:text-emerald-400">{e.meat_components ?? "—"}</span>
            </div>
            <div className="whitespace-pre-wrap text-[11px] text-slate-600 dark:text-slate-300">
              {e.snippet_text?.slice(0, 400) ?? ""}
            </div>
          </div>
        ))}
      </div>

      <h3 className="mt-5 text-[13px] font-bold text-slate-700 dark:text-slate-200">
        Appeals ({dispute.appeals?.length ?? 0})
      </h3>
      <div className="flex flex-col gap-2 mt-2">
        {(dispute.appeals ?? []).map((a) => (
          <div key={a.id} className="bg-purple-50 dark:bg-purple-950 p-2.5 rounded-md text-xs">
            <div className="flex justify-between">
              <span className="font-semibold text-slate-800 dark:text-slate-100">Round {a.appeal_round}</span>
              <span className={`${outcomeClasses(a.outcome)} px-1.5 py-0.5 rounded text-[10px] font-bold`}>
                {a.outcome.toUpperCase()}
              </span>
            </div>
            <div className="text-[11px] text-slate-600 dark:text-slate-300 mt-1">
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
    <div className="flex justify-between py-1.5 text-[13px] border-b border-slate-100 dark:border-slate-800">
      <span className="text-slate-500 dark:text-slate-400">{label}</span>
      <span className="text-slate-800 dark:text-slate-100 font-medium">{value}</span>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Modals                                                             */
/* ------------------------------------------------------------------ */

function Modal(props: { title: string; children: React.ReactNode; actions: React.ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 bg-slate-900/60 flex items-center justify-center z-[200]">
      <div className="bg-white dark:bg-slate-900 rounded-[10px] w-[720px] max-w-[95vw] max-h-[90vh] flex flex-col">
        <div className="px-5 py-4 border-b border-slate-200 dark:border-slate-700 flex justify-between items-center">
          <h3 className="text-base font-bold text-slate-800 dark:text-slate-100">{props.title}</h3>
          <button onClick={props.onClose} aria-label="Close" className="border-none bg-transparent cursor-pointer text-slate-500 dark:text-slate-400">
            <X size={18} />
          </button>
        </div>
        <div className="p-5 flex-1 overflow-y-auto">{props.children}</div>
        <div className="px-5 py-3 border-t border-slate-200 dark:border-slate-700 flex justify-end gap-2">
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
          <button onClick={props.onClose} className={BTN_SECONDARY}>Cancel</button>
          <button
            disabled={props.submitting}
            onClick={() => props.onSubmit(outcome, parseFloat(amount) || 0)}
            className={BTN_PRIMARY}
          >
            {props.submitting ? "Saving…" : "Record"}
          </button>
        </>
      }
    >
      <label className={LBL}>Outcome</label>
      <select value={outcome} onChange={(e) => setOutcome(e.target.value as any)} className={INP}>
        <option value="overturned">Overturned (won)</option>
        <option value="partial">Partial (won)</option>
        <option value="upheld">Upheld (lost)</option>
        <option value="withdrawn">Withdrawn (abandoned)</option>
      </select>

      <label className={LBL}>Recovered amount ($)</label>
      <input
        type="number" step="0.01" value={amount}
        onChange={(e) => setAmount(e.target.value)} className={INP}
        placeholder="0.00"
      />
    </Modal>
  );
}

function CreateModal(props: {
  onClose: () => void;
  onSubmit: (payload: any) => void;
  submitting: boolean;
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
          <button onClick={props.onClose} className={BTN_SECONDARY}>Cancel</button>
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
            className={BTN_PRIMARY}
          >
            {props.submitting ? "Saving…" : "Create"}
          </button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-3">
        <div><label className={LBL}>Patient ID</label><input value={form.patient_id} onChange={(e) => set("patient_id", e.target.value)} className={INP} /></div>
        <div><label className={LBL}>HCC code</label><input value={form.hcc_code} onChange={(e) => set("hcc_code", e.target.value)} className={INP} /></div>
        <div><label className={LBL}>ICD-10</label><input value={form.icd10} onChange={(e) => set("icd10", e.target.value)} className={INP} /></div>
        <div><label className={LBL}>Disputed by</label>
          <select value={form.disputed_by} onChange={(e) => set("disputed_by", e.target.value)} className={INP}>
            <option value="cms">CMS</option>
            <option value="payer">Payer</option>
            <option value="internal_audit">Internal audit</option>
          </select>
        </div>
        <div><label className={LBL}>Payer name</label><input value={form.payer_name} onChange={(e) => set("payer_name", e.target.value)} className={INP} /></div>
        <div><label className={LBL}>$ at risk</label><input type="number" value={form.financial_impact} onChange={(e) => set("financial_impact", e.target.value)} className={INP} /></div>
        <div className="col-span-2">
          <label className={LBL}>Denial reason</label>
          <textarea value={form.denial_reason_text} onChange={(e) => set("denial_reason_text", e.target.value)} className={`${INP} h-[60px]`} />
        </div>
        <div><label className={LBL}>Received date</label><input type="date" value={form.denial_received_at} onChange={(e) => set("denial_received_at", e.target.value)} className={INP} /></div>
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

function outcomeClasses(o: string): string {
  if (o === "overturned" || o === "partial") return "bg-emerald-50 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400";
  if (o === "upheld") return "bg-red-50 dark:bg-red-950 text-red-600 dark:text-red-400";
  if (o === "withdrawn") return "bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400";
  return "bg-amber-50 dark:bg-amber-950 text-amber-600 dark:text-amber-400";
}

const BTN_PRIMARY = "inline-flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 text-white border-none px-4 py-2 rounded-md text-[13px] font-semibold cursor-pointer disabled:opacity-50";

const BTN_SECONDARY = "bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-slate-700 px-3.5 py-2 rounded-md text-[13px] font-semibold cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-700";

const LBL = "block text-xs font-semibold text-slate-600 dark:text-slate-300 mb-1 mt-2";

const INP = "w-full px-2.5 py-2 border border-slate-200 dark:border-slate-700 rounded-md text-[13px] text-slate-800 dark:text-slate-100 bg-white dark:bg-slate-800";
