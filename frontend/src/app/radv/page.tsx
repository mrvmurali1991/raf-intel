"use client";

/**
 * RADV Audit Defense Workflow — Gap #3.
 *
 * Three views in one page:
 *   - List view  (no `run` selected): all audit runs for the tenant.
 *   - Detail view (`run` query param): 3-column layout
 *       [record list | record detail + decision panel | exposure simulator].
 *
 * Backend contract: see backend/app/routers/radv_audit_runs.py.
 */

import React, { useEffect, useMemo, useRef, useState } from "react";
import api from "@/lib/api";
import {
  ShieldCheck,
  FileText,
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Plus,
  Download,
  Send,
  ArrowLeft,
  DollarSign,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type SampleMethod = "random" | "stratified_hcc" | "high_risk_first";
type EvidenceStatus = "pending" | "complete" | "missing_meat" | "chart_requested";
type Decision = "pending" | "defensible" | "undefensible" | "needs_remediation";
type RunStatus = "prep" | "reviewing" | "complete" | "exported";

interface RunSummary {
  id: number;
  name: string;
  payment_year: number;
  sample_size: number;
  sample_method: SampleMethod;
  status: RunStatus;
  created_at: string;
  record_count: number;
  defensible_count: number;
  undefensible_count: number;
  remediation_count: number;
  total_exposure_dollars: number;
}

interface AuditRecord {
  id: number;
  patient_id: number;
  first_name?: string | null;
  last_name?: string | null;
  mrn?: string | null;
  sampled_hcc_codes: string[];
  evidence_status: EvidenceStatus;
  final_decision: Decision;
  reviewer_notes?: string | null;
  extrapolated_exposure_dollars: number;
  edps_rejected?: number;
}

interface RunDetail {
  id: number;
  name: string;
  payment_year: number;
  sample_size: number;
  sample_method: SampleMethod;
  status: RunStatus;
  assumed_fail_rate?: number | null;
  records: AuditRecord[];
  summary: {
    total_records: number;
    defensible: number;
    undefensible: number;
    needs_remediation: number;
    pending: number;
    total_exposure_dollars: number;
  };
}

interface SimulateResult {
  observed_exposure_dollars: number;
  simulated_exposure_dollars: number;
  assumed_fail_rate: number;
  extrapolation_multiplier: number;
  avg_hcc_payment_dollars: number;
  total_records: number;
  observed_undefensible: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CURRENT_YEAR = new Date().getFullYear();
const PRIMARY = "#0F766E";
const DANGER = "#DC2626";
const WARN = "#D97706";
const SUCCESS = "#16A34A";
const SUBTLE = "#64748B";

const decisionColor: Record<Decision, string> = {
  pending: SUBTLE,
  defensible: SUCCESS,
  undefensible: DANGER,
  needs_remediation: WARN,
};

const formatUsd = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function RadvPage() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const newRunTriggerRef = useRef<HTMLButtonElement | null>(null);

  // Hydrate `run` query param on mount and when navigating.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const r = params.get("run");
    setSelectedRunId(r ? Number(r) : null);
  }, []);

  // Persist `run` to URL.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    if (selectedRunId) url.searchParams.set("run", String(selectedRunId));
    else url.searchParams.delete("run");
    window.history.replaceState({}, "", url.toString());
  }, [selectedRunId]);

  async function loadRuns() {
    try {
      const res = await api.get<{ runs: RunSummary[] }>("/api/radv/audit-runs");
      setRuns(res.data.runs || []);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || "Failed to load audit runs";
      setError(msg);
    }
  }

  useEffect(() => {
    void loadRuns();
  }, []);

  return (
    <div style={{ minHeight: "100vh", backgroundColor: "#F8FAFC", padding: 24 }}>
      <div style={{ maxWidth: 1400, margin: "0 auto" }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            {selectedRunId && (
              <button
                onClick={() => setSelectedRunId(null)}
                aria-label="Back to runs list"
                style={{
                  display: "flex", alignItems: "center", gap: 4,
                  padding: "6px 10px", borderRadius: 6, border: "1px solid #E2E8F0",
                  backgroundColor: "#fff", cursor: "pointer", fontSize: 13,
                }}
              >
                <ArrowLeft size={14} /> All runs
              </button>
            )}
            <ShieldCheck size={28} color={PRIMARY} />
            <div>
              <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: "#0F172A" }}>
                RADV Audit Defense
              </h1>
              <p style={{ margin: "2px 0 0", fontSize: 13, color: SUBTLE }}>
                Mock-audit prep, decisions, MAO-004 re-submission, exposure simulator
              </p>
            </div>
          </div>
          {!selectedRunId && (
            <button
              ref={newRunTriggerRef}
              onClick={() => setCreating(true)}
              data-testid="radv-new-run"
              style={{
                display: "flex", alignItems: "center", gap: 6,
                padding: "10px 16px", borderRadius: 8, border: "none",
                backgroundColor: PRIMARY, color: "#fff", cursor: "pointer", fontWeight: 600,
              }}
            >
              <Plus size={16} /> New audit run
            </button>
          )}
        </div>

        {error && (
          <div style={{ marginBottom: 16, padding: 12, borderRadius: 8, backgroundColor: "#FEE2E2", color: DANGER, fontSize: 13 }}>
            {error}
          </div>
        )}

        {creating && (
          <CreateRunDialog
            triggerRef={newRunTriggerRef}
            onClose={() => setCreating(false)}
            onCreated={(id) => {
              setCreating(false);
              void loadRuns();
              setSelectedRunId(id);
            }}
          />
        )}

        {!selectedRunId ? (
          <RunList runs={runs} onOpen={setSelectedRunId} />
        ) : (
          <RunDetailView runId={selectedRunId} onChanged={loadRuns} />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Run list
// ---------------------------------------------------------------------------

function RunList({ runs, onOpen }: { runs: RunSummary[] | null; onOpen: (id: number) => void }) {
  if (runs === null) {
    return <div style={{ color: SUBTLE, padding: 24 }}>Loading…</div>;
  }
  if (runs.length === 0) {
    return (
      <div style={{ backgroundColor: "#fff", borderRadius: 12, padding: 48, textAlign: "center", border: "1px solid #E2E8F0" }}>
        <ShieldCheck size={36} color={SUBTLE} style={{ margin: "0 auto 12px" }} />
        <div style={{ fontWeight: 600, fontSize: 16, color: "#0F172A", marginBottom: 4 }}>
          No audit runs yet
        </div>
        <div style={{ color: SUBTLE, fontSize: 13 }}>
          Create one to sample N patients from a payment year and start defense prep.
        </div>
      </div>
    );
  }
  return (
    <div style={{ backgroundColor: "#fff", borderRadius: 12, border: "1px solid #E2E8F0", overflow: "hidden" }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ backgroundColor: "#F8FAFC", borderBottom: "1px solid #E2E8F0" }}>
            {["Name", "Year", "Sample", "Method", "Status", "Decided", "Exposure", ""].map((h) => (
              <th key={h} style={{ padding: "10px 14px", textAlign: "left", fontSize: 11, color: SUBTLE, fontWeight: 600, textTransform: "uppercase" }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => {
            const decided = (r.defensible_count || 0) + (r.undefensible_count || 0) + (r.remediation_count || 0);
            return (
              <tr key={r.id} style={{ borderBottom: "1px solid #F1F5F9" }}>
                <td style={{ padding: "12px 14px", fontWeight: 600, color: "#0F172A" }}>{r.name}</td>
                <td style={{ padding: "12px 14px", color: SUBTLE }}>{r.payment_year}</td>
                <td style={{ padding: "12px 14px", color: SUBTLE }}>{r.record_count}/{r.sample_size}</td>
                <td style={{ padding: "12px 14px", color: SUBTLE, fontSize: 12 }}>{r.sample_method}</td>
                <td style={{ padding: "12px 14px" }}>
                  <StatusBadge status={r.status} />
                </td>
                <td style={{ padding: "12px 14px", color: SUBTLE }}>{decided}/{r.record_count}</td>
                <td style={{ padding: "12px 14px", fontWeight: 600, color: r.total_exposure_dollars > 0 ? DANGER : "#0F172A" }}>
                  {formatUsd(Number(r.total_exposure_dollars || 0))}
                </td>
                <td style={{ padding: "12px 14px", textAlign: "right" }}>
                  <button
                    onClick={() => onOpen(r.id)}
                    style={{ padding: "6px 12px", borderRadius: 6, border: `1px solid ${PRIMARY}`, color: PRIMARY, backgroundColor: "#fff", cursor: "pointer", fontWeight: 600, fontSize: 12 }}
                  >
                    Open
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function StatusBadge({ status }: { status: RunStatus }) {
  const map: Record<RunStatus, { bg: string; color: string; label: string }> = {
    prep:      { bg: "#E0F2FE", color: "#0369A1", label: "Prep" },
    reviewing: { bg: "#FEF3C7", color: "#92400E", label: "Reviewing" },
    complete:  { bg: "#DCFCE7", color: "#166534", label: "Complete" },
    exported:  { bg: "#E0E7FF", color: "#3730A3", label: "Exported" },
  };
  const s = map[status];
  return (
    <span style={{ display: "inline-block", padding: "3px 10px", borderRadius: 999, backgroundColor: s.bg, color: s.color, fontSize: 11, fontWeight: 600 }}>
      {s.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Create dialog
// ---------------------------------------------------------------------------

function CreateRunDialog({
  onClose,
  onCreated,
  triggerRef,
}: {
  onClose: () => void;
  onCreated: (id: number) => void;
  triggerRef?: React.RefObject<HTMLButtonElement | null>;
}) {
  const [name, setName] = useState(`Q${Math.floor((new Date().getMonth() + 3) / 3)} ${CURRENT_YEAR} mock`);
  const [paymentYear, setPaymentYear] = useState(CURRENT_YEAR - 1);
  const [sampleSize, setSampleSize] = useState(50);
  const [sampleMethod, setSampleMethod] = useState<SampleMethod>("random");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const dialogRef = useRef<HTMLDivElement | null>(null);
  const firstInputRef = useRef<HTMLInputElement | null>(null);

  // Focus first input on mount
  useEffect(() => {
    firstInputRef.current?.focus();
  }, []);

  // Return focus to trigger on unmount
  useEffect(() => {
    return () => {
      triggerRef?.current?.focus();
    };
  }, [triggerRef]);

  // Focus trap + Escape handler
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const dialog = dialogRef.current;
      if (!dialog) return;
      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((el) => !el.hasAttribute("disabled"));
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  async function submit() {
    setSubmitting(true);
    setErr(null);
    try {
      const res = await api.post<RunDetail>("/api/radv/audit-runs", {
        name, payment_year: paymentYear, sample_size: sampleSize, sample_method: sampleMethod,
      });
      onCreated(res.data.id);
    } catch (e: unknown) {
      setErr((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="radv-dialog-title"
      style={{ position: "fixed", inset: 0, backgroundColor: "rgba(15,23,42,0.4)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 50 }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        style={{ backgroundColor: "#fff", borderRadius: 12, padding: 24, width: 460, boxShadow: "0 12px 40px rgba(0,0,0,0.15)" }}
      >
        <h2 id="radv-dialog-title" style={{ margin: "0 0 16px", fontSize: 18, fontWeight: 700 }}>New RADV audit run</h2>
        <Field label="Name">
          <input ref={firstInputRef} value={name} onChange={(e) => setName(e.target.value)}
            style={inputStyle} />
        </Field>
        <Field label="Payment year">
          <input type="number" value={paymentYear} onChange={(e) => setPaymentYear(Number(e.target.value))}
            style={inputStyle} />
        </Field>
        <Field label="Sample size (CMS: 200)">
          <input type="number" min={1} max={5000} value={sampleSize} onChange={(e) => setSampleSize(Number(e.target.value))}
            style={inputStyle} />
        </Field>
        <Field label="Sample method">
          <select value={sampleMethod} onChange={(e) => setSampleMethod(e.target.value as SampleMethod)}
            style={inputStyle}>
            <option value="random">Random</option>
            <option value="stratified_hcc">Stratified by HCC</option>
            <option value="high_risk_first">High-risk-first</option>
          </select>
        </Field>
        {err && <div role="alert" style={{ color: DANGER, fontSize: 12, marginBottom: 10 }}>{err}</div>}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onClose}
            style={{ padding: "8px 16px", borderRadius: 6, border: "1px solid #E2E8F0", backgroundColor: "#fff", cursor: "pointer" }}>
            Cancel
          </button>
          <button onClick={submit} disabled={submitting}
            data-testid="radv-create-submit"
            style={{ padding: "8px 16px", borderRadius: 6, border: "none", backgroundColor: PRIMARY, color: "#fff", cursor: submitting ? "wait" : "pointer", fontWeight: 600 }}>
            {submitting ? "Sampling…" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: "block", marginBottom: 12 }}>
      <div style={{ fontSize: 12, color: SUBTLE, fontWeight: 600, marginBottom: 4 }}>{label}</div>
      {children}
    </label>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%", padding: "8px 10px", borderRadius: 6, border: "1px solid #E2E8F0", fontSize: 14, boxSizing: "border-box",
};

// ---------------------------------------------------------------------------
// Run detail (3-column layout)
// ---------------------------------------------------------------------------

function RunDetailView({ runId, onChanged }: { runId: number; onChanged: () => void }) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [activeRecordId, setActiveRecordId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      const res = await api.get<RunDetail>(`/api/radv/audit-runs/${runId}`);
      setRun(res.data);
      if (!activeRecordId && res.data.records.length) {
        setActiveRecordId(res.data.records[0].id);
      }
    } catch (e: unknown) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Load failed");
    }
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void load(); }, [runId]);

  const activeRecord = useMemo(
    () => run?.records.find((r) => r.id === activeRecordId) || null,
    [run, activeRecordId],
  );

  async function patchRecord(decision?: Decision, evidence?: EvidenceStatus, notes?: string) {
    if (!activeRecord) return;
    setBusy(true);
    try {
      await api.put(`/api/radv/audit-runs/${runId}/records/${activeRecord.id}`, {
        final_decision: decision,
        evidence_status: evidence,
        reviewer_notes: notes,
      });
      await load();
      onChanged();
    } catch (e: unknown) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Update failed");
    } finally {
      setBusy(false);
    }
  }

  async function exportRun() {
    await api.post(`/api/radv/audit-runs/${runId}/export`);
    await load();
    onChanged();
  }

  async function resubmit() {
    const res = await api.post<{ item_count: number; batch_id: string }>(`/api/radv/audit-runs/${runId}/resubmit-rejected`);
    alert(`MAO-004 batch ${res.data.batch_id} generated with ${res.data.item_count} records`);
  }

  if (error) return <div style={{ color: DANGER }}>{error}</div>;
  if (!run) return <div style={{ color: SUBTLE }}>Loading run…</div>;

  return (
    <div>
      {/* Top stats bar */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12, marginBottom: 16 }}>
        <StatTile label="Records" value={`${run.summary.total_records}/${run.sample_size}`} />
        <StatTile label="Defensible" value={String(run.summary.defensible)} color={SUCCESS} />
        <StatTile label="Undefensible" value={String(run.summary.undefensible)} color={DANGER} />
        <StatTile label="Pending" value={String(run.summary.pending)} color={SUBTLE} />
        <StatTile label="Total exposure" value={formatUsd(run.summary.total_exposure_dollars)} color={run.summary.total_exposure_dollars > 0 ? DANGER : "#0F172A"} />
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 16, justifyContent: "flex-end" }}>
        <button onClick={resubmit}
          style={{ display: "flex", gap: 6, alignItems: "center", padding: "8px 14px", borderRadius: 6, border: `1px solid ${WARN}`, color: WARN, backgroundColor: "#fff", cursor: "pointer", fontWeight: 600 }}>
          <Send size={14} /> MAO-004 re-submit rejected
        </button>
        <button onClick={exportRun}
          style={{ display: "flex", gap: 6, alignItems: "center", padding: "8px 14px", borderRadius: 6, border: "none", backgroundColor: PRIMARY, color: "#fff", cursor: "pointer", fontWeight: 600 }}>
          <Download size={14} /> Export evidence
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "300px 1fr 320px", gap: 12, alignItems: "stretch" }}>
        {/* Column 1 — record list */}
        <div style={{ backgroundColor: "#fff", border: "1px solid #E2E8F0", borderRadius: 12, overflow: "auto", maxHeight: 700 }}>
          <div style={{ padding: "10px 14px", fontSize: 11, fontWeight: 700, color: SUBTLE, textTransform: "uppercase", borderBottom: "1px solid #F1F5F9" }}>
            Sampled records
          </div>
          {run.records.map((r) => {
            const sel = r.id === activeRecordId;
            return (
              <button
                key={r.id}
                onClick={() => setActiveRecordId(r.id)}
                data-testid={`radv-record-${r.id}`}
                style={{
                  display: "block", width: "100%", textAlign: "left",
                  padding: "10px 14px", border: "none",
                  borderBottom: "1px solid #F1F5F9",
                  backgroundColor: sel ? "#F0FDFA" : "#fff",
                  cursor: "pointer",
                  borderLeft: sel ? `3px solid ${PRIMARY}` : "3px solid transparent",
                }}
              >
                <div style={{ fontSize: 13, fontWeight: 600, color: "#0F172A" }}>
                  {r.first_name || ""} {r.last_name || `Patient #${r.patient_id}`}
                </div>
                <div style={{ fontSize: 11, color: SUBTLE, marginTop: 2 }}>
                  HCCs: {r.sampled_hcc_codes.join(", ") || "—"}
                </div>
                <div style={{ marginTop: 4, display: "flex", gap: 6, alignItems: "center" }}>
                  <span style={{ fontSize: 10, padding: "1px 6px", borderRadius: 999, backgroundColor: "#F8FAFC", color: decisionColor[r.final_decision], fontWeight: 600 }}>
                    {r.final_decision}
                  </span>
                </div>
              </button>
            );
          })}
        </div>

        {/* Column 2 — record detail + decision panel */}
        <div style={{ backgroundColor: "#fff", border: "1px solid #E2E8F0", borderRadius: 12, padding: 16 }}>
          {!activeRecord ? (
            <div style={{ color: SUBTLE }}>Select a record to review.</div>
          ) : (
            <>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
                <div>
                  <div style={{ fontSize: 16, fontWeight: 700, color: "#0F172A" }}>
                    {activeRecord.first_name} {activeRecord.last_name || `Patient #${activeRecord.patient_id}`}
                  </div>
                  <div style={{ fontSize: 12, color: SUBTLE }}>
                    MRN {activeRecord.mrn || "—"} · HCCs {activeRecord.sampled_hcc_codes.join(", ") || "—"}
                  </div>
                </div>
                <div style={{ fontSize: 12, color: SUBTLE }}>
                  Exposure: <strong style={{ color: activeRecord.extrapolated_exposure_dollars > 0 ? DANGER : "#0F172A" }}>
                    {formatUsd(Number(activeRecord.extrapolated_exposure_dollars || 0))}
                  </strong>
                </div>
              </div>

              <div style={{ display: "flex", gap: 16, padding: 12, backgroundColor: "#F8FAFC", borderRadius: 8, marginBottom: 16 }}>
                <FileText size={18} color={SUBTLE} />
                <div style={{ flex: 1, fontSize: 13, color: "#334155" }}>
                  MEAT evidence chain placeholder — see <code style={{ fontSize: 11 }}>/api/radv/audit-trail/{activeRecord.patient_id}/{activeRecord.sampled_hcc_codes[0]}</code>
                </div>
              </div>

              <div style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 12, color: SUBTLE, fontWeight: 600, marginBottom: 6 }}>Coder decision</div>
                <div style={{ display: "flex", gap: 8 }}>
                  <DecisionButton current={activeRecord.final_decision} value="defensible" onClick={() => patchRecord("defensible")} busy={busy} />
                  <DecisionButton current={activeRecord.final_decision} value="undefensible" onClick={() => patchRecord("undefensible")} busy={busy} />
                  <DecisionButton current={activeRecord.final_decision} value="needs_remediation" onClick={() => patchRecord("needs_remediation")} busy={busy} />
                </div>
              </div>

              <div>
                <div style={{ fontSize: 12, color: SUBTLE, fontWeight: 600, marginBottom: 6 }}>Reviewer notes</div>
                <textarea
                  defaultValue={activeRecord.reviewer_notes || ""}
                  rows={3}
                  data-testid="radv-notes"
                  onBlur={(e) => {
                    if (e.target.value !== (activeRecord.reviewer_notes || "")) {
                      void patchRecord(undefined, undefined, e.target.value);
                    }
                  }}
                  style={{ width: "100%", padding: 8, borderRadius: 6, border: "1px solid #E2E8F0", boxSizing: "border-box", fontSize: 13 }}
                />
              </div>
            </>
          )}
        </div>

        {/* Column 3 — exposure simulator */}
        <SimulatorPanel runId={runId} run={run} />
      </div>
    </div>
  );
}

function DecisionButton({
  current, value, onClick, busy,
}: { current: Decision; value: Decision; onClick: () => void; busy: boolean }) {
  const active = current === value;
  const c = decisionColor[value];
  return (
    <button
      onClick={onClick}
      disabled={busy}
      data-testid={`radv-decision-${value}`}
      style={{
        flex: 1, padding: "8px 10px", borderRadius: 6,
        border: `2px solid ${active ? c : "#E2E8F0"}`,
        backgroundColor: active ? c : "#fff", color: active ? "#fff" : c,
        cursor: busy ? "wait" : "pointer", fontWeight: 600, fontSize: 12,
        textTransform: "capitalize",
      }}
    >
      {value.replace("_", " ")}
    </button>
  );
}

function StatTile({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ backgroundColor: "#fff", border: "1px solid #E2E8F0", borderRadius: 10, padding: 12 }}>
      <div style={{ fontSize: 11, color: SUBTLE, fontWeight: 600, textTransform: "uppercase" }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, marginTop: 4, color: color || "#0F172A" }}>{value}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Simulator
// ---------------------------------------------------------------------------

function SimulatorPanel({ runId, run }: { runId: number; run: RunDetail }) {
  const initialRate = run.assumed_fail_rate != null
    ? Number(run.assumed_fail_rate)
    : (run.summary.total_records > 0
        ? run.summary.undefensible / run.summary.total_records
        : 0);
  const [rate, setRate] = useState<number>(initialRate);
  const [result, setResult] = useState<SimulateResult | null>(null);
  const [busy, setBusy] = useState(false);

  async function run_() {
    setBusy(true);
    try {
      const res = await api.post<SimulateResult>(`/api/radv/audit-runs/${runId}/simulate`, {
        assumed_fail_rate: rate,
      });
      setResult(res.data);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => { void run_(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [rate, run.summary.total_records, run.summary.undefensible]);

  return (
    <div style={{ backgroundColor: "#fff", border: "1px solid #E2E8F0", borderRadius: 12, padding: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <DollarSign size={18} color={PRIMARY} />
        <div style={{ fontSize: 14, fontWeight: 700, color: "#0F172A" }}>Revenue exposure simulator</div>
      </div>

      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 11, color: SUBTLE, fontWeight: 600 }}>Assumed fail rate</div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
          <input
            type="range" min={0} max={1} step={0.01} value={rate}
            onChange={(e) => setRate(Number(e.target.value))}
            data-testid="radv-simulate-slider"
            aria-label="Assumed fail rate"
            style={{ flex: 1 }}
          />
          <div style={{ fontWeight: 700, fontSize: 13, color: "#0F172A", minWidth: 50, textAlign: "right" }}>
            {(rate * 100).toFixed(0)}%
          </div>
        </div>
      </div>

      {busy && <div style={{ color: SUBTLE, fontSize: 12 }}><Loader2 size={12} className="spin" /> Calculating…</div>}

      {result && !busy && (
        <div data-testid="radv-simulate-result">
          <SimRow label="Observed (decided)" value={formatUsd(result.observed_exposure_dollars)} color={result.observed_exposure_dollars > 0 ? DANGER : "#0F172A"} />
          <SimRow label="Simulated total" value={formatUsd(result.simulated_exposure_dollars)} bold color={result.simulated_exposure_dollars > 0 ? DANGER : "#0F172A"} />
          <div style={{ marginTop: 12, padding: 8, backgroundColor: "#FEF3C7", borderRadius: 6, fontSize: 11, color: "#78350F" }}>
            <AlertTriangle size={11} style={{ verticalAlign: "middle" }} />{" "}
            CMS extrapolation: each error × {result.extrapolation_multiplier.toFixed(0)}× × {formatUsd(result.avg_hcc_payment_dollars)}/HCC
          </div>
        </div>
      )}

      <style>{`.spin { animation: rspin 1s linear infinite; } @keyframes rspin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

function SimRow({ label, value, bold, color }: { label: string; value: string; bold?: boolean; color?: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px dashed #F1F5F9" }}>
      <span style={{ fontSize: 12, color: SUBTLE }}>{label}</span>
      <span style={{ fontSize: bold ? 14 : 13, fontWeight: bold ? 700 : 500, color: color || "#0F172A" }}>{value}</span>
    </div>
  );
}
