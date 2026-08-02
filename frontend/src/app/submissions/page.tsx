"use client";

import React, { useState, useCallback, useRef, useMemo } from "react";
import dynamic from "next/dynamic";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { DataQualityBanner } from "@/components/DataQualityBanner";
import {
  Send,
  RefreshCw,
  AlertTriangle,
  X,
  ChevronDown,
  ChevronUp,
  CheckCircle,
  XCircle,
  Clock,
  Loader2,
  Download,
  Upload,
  FileText,
  AlertCircle,
  DollarSign,
  BarChart2,
  Calendar,
  Play,
  Eye,
  List,
  ShieldCheck,
  FileCheck,
  Inbox,
} from "lucide-react";
import { PageHeader, EmptyState } from "@/components/healthcare-ui";
import { MetricCard } from "@/components/ui/metric-card";

// ─────────────────────────────────────────────
// Lazy-loaded heavy panels (deferred from initial paint)
// ─────────────────────────────────────────────

const LazyGenerateDialog = dynamic(
  () => import("./SubmissionsDialogsPanels").then((m) => ({ default: m.GenerateDialog })),
  { ssr: false, loading: () => null }
);

const LazyUploadResponseDialog = dynamic(
  () => import("./SubmissionsDialogsPanels").then((m) => ({ default: m.UploadResponseDialog })),
  { ssr: false, loading: () => null }
);

const LazyBatchDetailPanel = dynamic(
  () => import("./SubmissionsDialogsPanels").then((m) => ({ default: m.BatchDetailPanel })),
  {
    ssr: false,
    loading: () => (
      <div className="flex items-center justify-center p-12 gap-2.5 text-slate-500 dark:text-slate-400">
        <div className="w-5 h-5 border-[3px] border-slate-200 dark:border-slate-700 border-t-blue-600 rounded-full animate-spin" />
        <span className="text-sm">Loading detail…</span>
      </div>
    ),
  }
);

// ─────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────

type SubmissionType = "RAPS" | "EDPS";
type SweepType = "Initial" | "Mid-Year" | "Final" | "Supplemental";
type BatchStatus =
  | "draft"
  | "validating"
  | "validated"
  | "submitted"
  | "accepted"
  | "rejected"
  | "partial"
  | "error";

type DetailTab = "records" | "validation" | "responses" | "reconciliation";

interface SubmissionBatch {
  id: string;
  batch_id: string;
  submission_type: SubmissionType;
  payment_year: number;
  sweep_type: SweepType;
  total_records: number;
  accepted_records: number;
  rejected_records: number;
  status: BatchStatus;
  submitted_at: string | null;
  created_at: string;
  validation_errors: number;
  validation_warnings: number;
}

interface SubmissionRecord {
  id: string;
  patient_name: string;
  patient_id: string;
  icd10_code: string;
  hcc_code: number | null;
  hcc_description: string | null;
  date_of_service: string;
  through_date: string;
  provider_id: string;
  validation_status: "pass" | "warning" | "error";
  cms_status: "accepted" | "rejected" | "pending" | null;
  rejection_reason: string | null;
}

interface ValidationIssue {
  rule_id: string;
  rule_name: string;
  severity: "error" | "warning";
  count: number;
  affected_records: string[];
  description: string;
  recommendation: string;
}

interface ResponseFile {
  id: string;
  file_name: string;
  file_type: "MAO-002" | "MAO-004";
  uploaded_at: string;
  records_parsed: number;
  accepted: number;
  rejected: number;
  status: "parsed" | "processing" | "error";
}

interface ReconciliationEntry {
  hcc_code: number;
  hcc_description: string;
  patient_count: number;
  risk_score_delta: number;
  payment_delta: number;
  cms_status: "accepted" | "rejected" | "pending";
}

interface BatchDetail {
  batch: SubmissionBatch;
  records: SubmissionRecord[];
  validation_issues: ValidationIssue[];
  response_files: ResponseFile[];
  reconciliation: ReconciliationEntry[];
  total_payment_impact: number;
  risk_score_adjustment: number;
}

interface SubmissionsStats {
  total_batches: number;
  records_submitted: number;
  acceptance_rate: number;
  pending_validation: number;
  upcoming_deadlines: number;
}

interface Deadline {
  name: string;
  type: SubmissionType;
  payment_year: number;
  sweep_type: SweepType;
  due_date: string;
  days_remaining: number;
}

// ─────────────────────────────────────────────
// API Helpers
// ─────────────────────────────────────────────

async function fetchStats(): Promise<SubmissionsStats> {
  const { data } = await api.get(`/api/submissions/stats`);
  return data;
}

async function fetchBatches(): Promise<SubmissionBatch[]> {
  const { data } = await api.get(`/api/submissions/batches`);
  return Array.isArray(data) ? data : (data?.items ?? data?.batches ?? []);
}

async function fetchDeadlines(): Promise<Deadline[]> {
  const { data } = await api.get(`/api/submissions/schedule`);
  const raw = Array.isArray(data) ? data : (data?.schedule ?? []);
  return raw.map((d: any) => ({
    name: d.description ?? d.name ?? '',
    type: d.submission_type ?? d.type ?? 'RAPS',
    payment_year: d.payment_year ?? new Date().getFullYear(),
    sweep_type: d.sweep_type ?? 'Initial',
    due_date: d.deadline_date ?? d.due_date ?? '',
    days_remaining: d.days_until ?? d.days_remaining ?? 0,
  }));
}

async function fetchBatchDetail(batchId: string): Promise<BatchDetail> {
  const { data } = await api.get(`/api/submissions/batches/${batchId}`);
  return data;
}

// ─────────────────────────────────────────────
// Status Badge
// ─────────────────────────────────────────────

function StatusBadge({ status }: { status: BatchStatus }) {
  const map: Record<BatchStatus, { label: string; cls: string; dotCls: string; icon: React.ReactNode }> = {
    draft:      { label: "Draft",          cls: "bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300",           dotCls: "bg-slate-400",          icon: <Clock size={11} /> },
    validating: { label: "Validating",     cls: "bg-blue-600/10 text-blue-700 dark:text-blue-300",                             dotCls: "bg-blue-500",           icon: <Loader2 size={11} className="animate-spin" /> },
    validated:  { label: "Validated",      cls: "bg-emerald-50 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400",    dotCls: "bg-emerald-500",        icon: <CheckCircle size={11} /> },
    submitted:  { label: "Submitted",      cls: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",                    dotCls: "bg-emerald-500",        icon: <Send size={11} /> },
    accepted:   { label: "Accepted",       cls: "bg-emerald-100 dark:bg-emerald-900 text-emerald-600 dark:text-emerald-400",   dotCls: "bg-emerald-500",        icon: <CheckCircle size={11} /> },
    rejected:   { label: "Rejected",       cls: "bg-red-100 dark:bg-red-900 text-red-600 dark:text-red-400",                   dotCls: "bg-red-500",            icon: <XCircle size={11} /> },
    partial:    { label: "Partial Accept", cls: "bg-amber-50 dark:bg-amber-950 text-amber-600 dark:text-amber-400",            dotCls: "bg-amber-500",          icon: <AlertCircle size={11} /> },
    error:      { label: "Error",          cls: "bg-red-50 dark:bg-red-950 text-red-500 dark:text-red-400",                    dotCls: "bg-red-500",            icon: <XCircle size={11} /> },
  };
  const cfg = map[status] ?? { label: status, cls: "bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400", dotCls: "bg-slate-400", icon: null };
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold whitespace-nowrap border border-current/10 ${cfg.cls}`}>
      <span className={`w-[7px] h-[7px] rounded-full shrink-0 ${cfg.dotCls}`} />
      {cfg.icon}
      {cfg.label}
    </span>
  );
}

function TypeBadge({ type }: { type: SubmissionType }) {
  const isRAPS = type === "RAPS";
  return (
    <span className={`inline-flex items-center px-2 py-[3px] rounded-md text-[11px] font-bold tracking-wide border ${
      isRAPS
        ? "bg-violet-50 dark:bg-violet-950 text-violet-600 dark:text-violet-400 border-violet-500/20"
        : "bg-blue-50 dark:bg-blue-950 text-blue-700 dark:text-blue-300 border-blue-500/20"
    }`}>
      {type}
    </span>
  );
}

function ValidationBadge({ status }: { status: "pass" | "warning" | "error" }) {
  const map = {
    pass:    { label: "Pass",    cls: "bg-emerald-50 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400" },
    warning: { label: "Warning", cls: "bg-amber-50 dark:bg-amber-950 text-amber-600 dark:text-amber-400" },
    error:   { label: "Error",   cls: "bg-red-50 dark:bg-red-950 text-red-500 dark:text-red-400" },
  };
  const cfg = map[status];
  return (
    <span className={`px-[7px] py-[2px] rounded text-[11px] font-semibold ${cfg.cls}`}>
      {cfg.label}
    </span>
  );
}

function CmsStatusBadge({ status }: { status: "accepted" | "rejected" | "pending" | null }) {
  if (!status) return <span className="text-slate-400 dark:text-slate-500 text-xs">—</span>;
  const map = {
    accepted: { label: "Accepted", cls: "bg-emerald-50 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400" },
    rejected: { label: "Rejected", cls: "bg-red-50 dark:bg-red-950 text-red-600 dark:text-red-400" },
    pending:  { label: "Pending",  cls: "bg-amber-50 dark:bg-amber-950 text-amber-600 dark:text-amber-400" },
  };
  const cfg = map[status];
  return (
    <span className={`px-[7px] py-[2px] rounded text-[11px] font-semibold ${cfg.cls}`}>
      {cfg.label}
    </span>
  );
}

// ─────────────────────────────────────────────
// Deadline Banner
// ─────────────────────────────────────────────

function DeadlinesBanner({ deadlines }: { deadlines: Deadline[] }) {
  const sorted = [...deadlines].sort((a, b) => a.days_remaining - b.days_remaining);

  function deadlineClasses(days: number): { cardCls: string; textCls: string; pillCls: string; pillLabel: string; opacity: string } {
    if (days < 0) {
      return {
        cardCls: "bg-red-50 dark:bg-red-950 border-red-500/40",
        textCls: "text-red-600 dark:text-red-400",
        pillCls: "bg-red-100 dark:bg-red-900 text-red-600 dark:text-red-400 border-red-600/20",
        pillLabel: "Overdue",
        opacity: "opacity-70",
      };
    }
    if (days <= 7) {
      return {
        cardCls: "bg-amber-50 dark:bg-amber-950 border-amber-500/40",
        textCls: "text-amber-600 dark:text-amber-400",
        pillCls: "bg-amber-100 dark:bg-amber-900 text-amber-600 dark:text-amber-400 border-amber-600/20",
        pillLabel: "Closing soon",
        opacity: "",
      };
    }
    if (days <= 30) {
      return {
        cardCls: "bg-amber-50 dark:bg-amber-950 border-amber-500/30",
        textCls: "text-amber-600 dark:text-amber-400",
        pillCls: "",
        pillLabel: "",
        opacity: "",
      };
    }
    return {
      cardCls: "bg-emerald-50 dark:bg-emerald-950 border-emerald-500/40",
      textCls: "text-emerald-600 dark:text-emerald-400",
      pillCls: "",
      pillLabel: "",
      opacity: "",
    };
  }

  function deadlineCountLabel(days: number): string {
    if (days < 0) return `Closed ${Math.abs(days)} day${Math.abs(days) === 1 ? "" : "s"} ago`;
    if (days === 0) return "Due today";
    return `${days} day${days === 1 ? "" : "s"} left`;
  }

  return (
    <div className="sub-fade-up-2 flex flex-col gap-2 mb-6">
      <div className="flex items-center gap-1.5 mb-1">
        <Calendar size={14} className="text-muted-foreground" />
        <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-widest">
          Submission Deadlines
        </span>
      </div>
      <div className="flex gap-2.5 flex-wrap">
        {sorted.map((d, i) => {
          const c = deadlineClasses(d.days_remaining);
          const isOverdue = d.days_remaining < 0;
          return (
            <div
              key={`${d.name}-${i}`}
              className={`hover-lift flex-[1_1_260px] border rounded-[10px] px-[18px] py-3.5 flex items-center justify-between gap-3 ${c.cardCls} ${c.opacity}`}
              style={{ animation: `fadeInUp 0.4s ease-out ${0.08 * i}s both` }}
              aria-label={`${d.name}: ${deadlineCountLabel(d.days_remaining)}`}
            >
              <div className="flex flex-col gap-1">
                <div className="flex items-center gap-1.5">
                  <span className={`text-[13px] font-semibold text-slate-800 dark:text-slate-100 ${isOverdue ? "line-through decoration-slate-400" : ""}`}>
                    {d.name}
                  </span>
                  {c.pillLabel && (
                    <span className={`inline-flex items-center px-2 py-[2px] rounded-full text-[10px] font-bold uppercase tracking-wide whitespace-nowrap border ${c.pillCls}`} role="status">
                      {c.pillLabel}
                    </span>
                  )}
                </div>
                <span className="text-[11px] text-slate-500 dark:text-slate-400">
                  PY{d.payment_year} · {d.sweep_type} · Due {new Date(d.due_date).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
                </span>
              </div>
              <div className="flex flex-col items-end gap-0.5 shrink-0">
                <span className={`text-[13px] font-bold leading-snug text-right whitespace-nowrap ${c.textCls}`}>
                  {deadlineCountLabel(d.days_remaining)}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
// Batches Table
// ─────────────────────────────────────────────

interface BatchesTableProps {
  batches: SubmissionBatch[];
  expandedId: string | null;
  onExpand: (id: string | null) => void;
  onValidate: (id: string) => void;
  onDownload: (id: string) => void;
  onUploadResponse: (id: string, name: string) => void;
  onViewErrors: (id: string) => void;
}

function BatchesTable({
  batches,
  expandedId,
  onExpand,
  onValidate,
  onDownload,
  onUploadResponse,
  onViewErrors,
}: BatchesTableProps) {
  if (batches.length === 0) {
    return (
      <div className="premium-card p-12 text-center">
        <div>
          <EmptyState
            icon={<Send size={28} />}
            title="No CMS submission batches yet — this is unusual"
            description="CMS submissions are required for MA plan payment. Verify the submission pipeline is running and generate your first batch above."
          />
        </div>
      </div>
    );
  }

  return (
    <div className="overflow-hidden">
      <div className="overflow-x-auto">
        <table aria-label="CMS submission batches" className="w-full border-collapse" style={{ minWidth: 900 }}>
          <thead>
            <tr>
              <th scope="col" className="px-3.5 py-2.5 text-[11px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-widest text-left border-b-2 border-slate-200 dark:border-slate-700 bg-gradient-to-b from-slate-50 dark:from-slate-800 to-white dark:to-slate-900 whitespace-nowrap w-10"><span className="sr-only">Expand</span></th>
              {["Batch ID", "Type", "PY", "Sweep"].map(h => (
                <th key={h} scope="col" className="px-3.5 py-2.5 text-[11px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-widest text-left border-b-2 border-slate-200 dark:border-slate-700 bg-gradient-to-b from-slate-50 dark:from-slate-800 to-white dark:to-slate-900 whitespace-nowrap">{h}</th>
              ))}
              <th scope="col" className="px-3.5 py-2.5 text-[11px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-widest text-right border-b-2 border-slate-200 dark:border-slate-700 bg-gradient-to-b from-slate-50 dark:from-slate-800 to-white dark:to-slate-900 whitespace-nowrap">Records</th>
              {["Status", "Submitted", "Actions"].map(h => (
                <th key={h} scope="col" className="px-3.5 py-2.5 text-[11px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-widest text-left border-b-2 border-slate-200 dark:border-slate-700 bg-gradient-to-b from-slate-50 dark:from-slate-800 to-white dark:to-slate-900 whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {batches.map((b) => {
              const isExpanded = expandedId === b.id;
              const acceptPct = b.total_records > 0 ? Math.round((b.accepted_records / b.total_records) * 100) : 0;

              return (
                <React.Fragment key={b.id}>
                  <tr className={`sub-table-row ${isExpanded ? "bg-blue-50 dark:bg-blue-950" : ""}`} style={{ animationDelay: `${0.03 * batches.indexOf(b)}s` }}>
                    <td className="px-3.5 py-3.5 text-[13px] text-slate-700 dark:text-slate-200 border-b border-slate-100 dark:border-slate-800 align-middle transition-colors" style={{ padding: "12px 8px 12px 14px" }}>
                      <button
                        onClick={() => onExpand(isExpanded ? null : b.id)}
                        className="w-6 h-6 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 cursor-pointer flex items-center justify-center text-slate-500 dark:text-slate-400 shrink-0"
                        aria-label={isExpanded ? "Collapse row" : "Expand row"}
                        aria-expanded={isExpanded}
                      >
                        {isExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                      </button>
                    </td>

                    <td className="px-3.5 py-3.5 text-[13px] text-slate-700 dark:text-slate-200 border-b border-slate-100 dark:border-slate-800 align-middle">
                      <span className="font-mono font-bold text-slate-800 dark:text-slate-100 text-[13px]">
                        {b.batch_id}
                      </span>
                    </td>

                    <td className="px-3.5 py-3.5 text-[13px] text-slate-700 dark:text-slate-200 border-b border-slate-100 dark:border-slate-800 align-middle"><TypeBadge type={b.submission_type} /></td>

                    <td className="px-3.5 py-3.5 text-[13px] text-slate-700 dark:text-slate-200 border-b border-slate-100 dark:border-slate-800 align-middle font-semibold">PY{b.payment_year}</td>

                    <td className="px-3.5 py-3.5 text-xs text-slate-600 dark:text-slate-300 border-b border-slate-100 dark:border-slate-800 align-middle">{b.sweep_type}</td>

                    <td className="px-3.5 py-3.5 text-[13px] text-slate-700 dark:text-slate-200 border-b border-slate-100 dark:border-slate-800 align-middle text-right">
                      <div className="flex flex-col items-end gap-[3px]">
                        <span className="font-bold text-slate-800 dark:text-slate-100">
                          {b.total_records?.toLocaleString() ?? "0"}
                        </span>
                        <div className="flex gap-2 text-[11px]">
                          <span className="text-emerald-600 dark:text-emerald-400">
                            {b.accepted_records?.toLocaleString() ?? "0"} acc
                          </span>
                          {b.rejected_records > 0 && (
                            <span className="text-red-500 dark:text-red-400">
                              {b.rejected_records?.toLocaleString() ?? "0"} rej
                            </span>
                          )}
                        </div>
                        {b.total_records > 0 && (
                          <div className="h-[3px] w-[72px] rounded-sm bg-slate-200 dark:bg-slate-700 overflow-hidden">
                            <div
                              className={`h-full rounded-sm transition-[width] duration-400 ${acceptPct >= 90 ? "bg-emerald-500" : acceptPct >= 70 ? "bg-amber-500" : "bg-red-500"}`}
                              style={{ width: `${acceptPct}%` }}
                            />
                          </div>
                        )}
                      </div>
                    </td>

                    <td className="px-3.5 py-3.5 text-[13px] text-slate-700 dark:text-slate-200 border-b border-slate-100 dark:border-slate-800 align-middle"><StatusBadge status={b.status} /></td>

                    <td className="px-3.5 py-3.5 text-xs text-slate-500 dark:text-slate-400 border-b border-slate-100 dark:border-slate-800 align-middle">
                      {b.submitted_at
                        ? new Date(b.submitted_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
                        : <span className="text-muted-foreground">—</span>}
                    </td>

                    <td className="px-3.5 py-3.5 text-[13px] text-slate-700 dark:text-slate-200 border-b border-slate-100 dark:border-slate-800 align-middle">
                      <div className="flex gap-1">
                        <ActionButton icon={<ShieldCheck size={13} />} label="Validate" onClick={() => onValidate(b.id)} />
                        <ActionButton icon={<Download size={13} />} label="Download" onClick={() => onDownload(b.id)} />
                        <ActionButton icon={<Upload size={13} />} label="Upload Response" onClick={() => onUploadResponse(b.id, b.batch_id)} />
                        {(b.validation_errors > 0 || b.rejected_records > 0) && (
                          <ActionButton icon={<AlertCircle size={13} />} label="View Errors" onClick={() => onViewErrors(b.id)} variant="danger" />
                        )}
                      </div>
                    </td>
                  </tr>

                  {isExpanded && (
                    <tr>
                      <td colSpan={9} className="px-4 pb-4 bg-slate-50 dark:bg-slate-800">
                        <LazyBatchDetailPanel
                          batchId={b.id}
                          onClose={() => onExpand(null)}
                          onUploadResponse={onUploadResponse}
                        />
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ActionButton({
  icon,
  label,
  onClick,
  variant,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  variant?: "danger";
}) {
  return (
    <button
      onClick={onClick}
      title={label}
      aria-label={label}
      className={`flex items-center gap-1 px-2.5 py-[5px] rounded-md border text-[11px] font-semibold cursor-pointer whitespace-nowrap transition-all duration-150 hover:-translate-y-px ${
        variant === "danger"
          ? "border-red-300 dark:border-red-700 bg-white dark:bg-slate-800 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950 hover:border-red-400"
          : "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-700 hover:border-slate-300 dark:hover:border-slate-600 hover:text-slate-700 dark:hover:text-slate-200"
      }`}
    >
      {icon}
      <span className="hidden xl:inline">{label}</span>
    </button>
  );
}

// ─────────────────────────────────────────────
// Main Page
// ─────────────────────────────────────────────

export default function SubmissionsPage() {
  const queryClient = useQueryClient();
  const [showGenerate, setShowGenerate] = useState(false);
  const [expandedBatch, setExpandedBatch] = useState<string | null>(null);
  const [uploadTarget, setUploadTarget] = useState<{ id: string; name: string } | null>(null);
  const [filterType, setFilterType] = useState<SubmissionType | "ALL">("ALL");
  const [filterStatus, setFilterStatus] = useState<BatchStatus | "ALL">("ALL");

  const statsQuery = useQuery({ queryKey: ["submissions-stats"], queryFn: fetchStats });
  const batchesQuery = useQuery({ queryKey: ["submissions-batches"], queryFn: fetchBatches });
  const deadlinesQuery = useQuery({ queryKey: ["submissions-deadlines"], queryFn: fetchDeadlines });

  const queryError = batchesQuery.isError;

  const rawStats = statsQuery.data as Record<string, unknown> | undefined;
  const stats = {
    total_batches: (rawStats?.total_batches as number) ?? 0,
    records_submitted: (rawStats?.records_submitted as number) ?? (rawStats?.total_records as number) ?? 0,
    acceptance_rate: (rawStats?.acceptance_rate as number) ?? 0,
    pending_validation: (rawStats?.pending_validation as number) ?? (rawStats?.total_invalid as number) ?? 0,
    upcoming_deadlines: Array.isArray(rawStats?.upcoming_deadlines)
      ? (rawStats!.upcoming_deadlines as unknown[]).length
      : (rawStats?.upcoming_deadlines as number) ?? 0,
  };
  const deadlines = deadlinesQuery.data ?? [];

  const batches = useMemo(() => {
    const all = batchesQuery.data ?? [];
    return all.filter((b) => {
      if (filterType !== "ALL" && b.submission_type !== filterType) return false;
      if (filterStatus !== "ALL" && b.status !== filterStatus) return false;
      return true;
    });
  }, [batchesQuery.data, filterType, filterStatus]);

  function handleRefresh() {
    queryClient.invalidateQueries({ queryKey: ["submissions-stats"] });
    queryClient.invalidateQueries({ queryKey: ["submissions-batches"] });
  }

  function handleValidate(id: string) {
    queryClient.invalidateQueries({ queryKey: ["submission-batch-detail", id] });
  }

  function handleDownload(id: string) {
    window.open(`/api/submissions/batches/${id}/download`, "_blank");
  }

  function handleViewErrors(id: string) {
    setExpandedBatch(id);
  }

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-900">
      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        @keyframes fadeInUp { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        .sub-fade-in { animation: fadeIn 0.4s ease-out both; }
        .sub-fade-up-1 { animation: fadeInUp 0.45s ease-out 0.05s both; }
        .sub-fade-up-2 { animation: fadeInUp 0.45s ease-out 0.12s both; }
        .sub-fade-up-3 { animation: fadeInUp 0.45s ease-out 0.2s both; }
        .sub-table-row { animation: fadeInUp 0.35s ease-out both; }
        .sub-table-row:hover { background-color: rgba(248,250,252,0.5) !important; }
        :is(.dark) .sub-table-row:hover { background-color: rgba(30,41,59,0.5) !important; }
        .sub-gradient-btn { background: linear-gradient(135deg, #2563EB 0%, #1D4ED8 100%); box-shadow: 0 2px 8px rgba(37,99,235,0.35); transition: all 0.2s ease; }
        .sub-gradient-btn:hover { box-shadow: 0 4px 16px rgba(37,99,235,0.45); transform: translateY(-1px); }
        .sub-outline-btn { transition: all 0.18s ease; }
        .sub-outline-btn:hover { border-color: #3B82F6; color: #2563EB; }
        :is(.dark) .sub-outline-btn:hover { border-color: #60A5FA; color: #60A5FA; background-color: rgba(37,99,235,0.1); }
        @media (max-width: 640px) { .rci-page-pad-desktop { padding: 20px 16px !important; } }
        button:focus-visible { outline: 2px solid #2563EB; outline-offset: 2px; border-radius: 4px; }
      `}</style>

      {queryError && (
        <div className="mx-7 mt-4 px-4 py-3 rounded-[10px] border border-red-500/40 bg-red-50 dark:bg-red-950 text-red-600 dark:text-red-400 text-[13px] font-semibold flex items-center justify-between gap-2" role="alert">
          <div className="flex items-center gap-2">
            <AlertCircle size={15} className="shrink-0" />
            <span>
              {(batchesQuery.error as any)?.response?.data?.detail ??
                (batchesQuery.error as any)?.message ??
                "Failed to load submission batches."}
            </span>
          </div>
          <button
            onClick={() => batchesQuery.refetch()}
            className="px-3 py-1 rounded-md border border-red-500/40 bg-white dark:bg-slate-800 text-red-600 dark:text-red-400 font-semibold text-xs cursor-pointer shrink-0"
          >
            Retry
          </button>
        </div>
      )}

      <div className="rci-page-pad-desktop" style={{ padding: "28px 28px 48px", maxWidth: 1440, margin: "0 auto" }}>
        <DataQualityBanner />

        <PageHeader
          title="CMS Submissions"
          subtitle="Manage RAPS and EDPS submissions to the Centers for Medicare & Medicaid Services"
          icon={<Send size={22} />}
          actions={
            <div className="flex gap-2">
              <button
                onClick={handleRefresh}
                className="sub-outline-btn flex items-center gap-1.5 px-3.5 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 font-semibold text-[13px] cursor-pointer"
                aria-label="Refresh data"
              >
                <RefreshCw size={14} />
                Refresh
              </button>
              <button
                onClick={() => setShowGenerate(true)}
                className="sub-gradient-btn flex items-center gap-1.5 px-4 py-2 rounded-lg border-none text-white font-bold text-[13px] cursor-pointer"
              >
                <Send size={14} />
                Generate Submission
              </button>
            </div>
          }
        />

        {/* Stats Row */}
        <div className="sub-fade-up-1 grid gap-4 mb-6" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
          {statsQuery.isLoading ? (
            Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-[10px] p-5 flex flex-col gap-2.5" aria-hidden="true">
                <div className="h-3 w-3/5 rounded-md bg-slate-100 dark:bg-slate-700" />
                <div className="h-7 w-2/5 rounded-md bg-slate-100 dark:bg-slate-700" />
                <div className="h-2.5 w-4/5 rounded-md bg-slate-100 dark:bg-slate-700" />
              </div>
            ))
          ) : statsQuery.isError ? (
            <div className="col-span-full bg-red-50 dark:bg-red-950 border border-red-500/40 rounded-[10px] px-4 py-3 flex items-center gap-2" role="alert">
              <AlertCircle size={15} className="text-red-600 dark:text-red-400" />
              <span className="text-[13px] text-red-600 dark:text-red-400 font-semibold">
                Failed to load submission statistics.
              </span>
            </div>
          ) : (
            <>
              <MetricCard label="Total Batches" value={stats.total_batches} icon={<FileText size={18} />} subtitle="All submission batches" />
              <MetricCard label="Records Submitted" value={stats.records_submitted?.toLocaleString() ?? "0"} icon={<Send size={18} />} intent="success" subtitle="Across all batches" />
              <MetricCard label="Acceptance Rate" value={`${(stats.acceptance_rate ?? 0).toFixed(1)}%`} icon={<CheckCircle size={18} />} intent="success" subtitle="CMS accepted records" delta={1.2} />
              <MetricCard label="Pending Validation" value={stats.pending_validation} icon={<Clock size={18} />} intent="warning" subtitle="Awaiting validation run" />
              <MetricCard label="Upcoming Deadlines" value={stats.upcoming_deadlines} icon={<Calendar size={18} />} intent={deadlines.some((d) => d.days_remaining < 7) ? "danger" : "warning"} subtitle="Within 30 days" />
            </>
          )}
        </div>

        {/* Deadlines Banner */}
        {deadlinesQuery.isLoading ? (
          <div className="flex gap-2.5 mb-6 flex-wrap">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="flex-[1_1_260px] h-[70px] rounded-[10px] bg-slate-100 dark:bg-slate-800" aria-hidden="true" />
            ))}
          </div>
        ) : deadlinesQuery.isError ? (
          <div className="mb-6 px-4 py-3 rounded-[10px] border border-amber-500/40 bg-amber-50 dark:bg-amber-950 flex items-center gap-2" role="alert">
            <AlertTriangle size={15} className="text-amber-600 dark:text-amber-400" />
            <span className="text-[13px] text-amber-600 dark:text-amber-400 font-semibold">
              Could not load submission deadlines.
            </span>
          </div>
        ) : deadlines.length > 0 ? (
          <DeadlinesBanner deadlines={deadlines} />
        ) : null}

        {/* Batches section */}
        <div className="premium-card sub-fade-up-3 overflow-hidden">
          {/* Table header & filters */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 dark:border-slate-700 gap-3 flex-wrap">
            <div className="flex items-center gap-2">
              <BarChart2 size={16} className="text-blue-600 dark:text-blue-400" />
              <span className="text-[15px] font-bold text-slate-900 dark:text-slate-50">
                Submission Batches
              </span>
              <span className="px-2 py-[2px] rounded-full text-[11px] font-semibold bg-blue-600/10 text-blue-600 dark:text-blue-400">
                {batches.length}
              </span>
            </div>

            <div className="flex gap-1.5 flex-wrap">
              <div className="flex gap-1">
                {(["ALL", "RAPS", "EDPS"] as const).map((t) => (
                  <button
                    key={t}
                    onClick={() => setFilterType(t)}
                    className={`px-3 py-[5px] rounded-md border text-xs font-semibold cursor-pointer transition-all ${
                      filterType === t
                        ? "border-blue-600 bg-blue-50 dark:bg-blue-950 text-blue-700 dark:text-blue-300"
                        : "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400"
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>

              <div className="w-px bg-slate-200 dark:bg-slate-700" />

              <select
                value={filterStatus}
                onChange={(e) => setFilterStatus(e.target.value as BatchStatus | "ALL")}
                className="px-2.5 py-[5px] rounded-md border border-slate-200 dark:border-slate-700 text-xs text-slate-600 dark:text-slate-300 bg-white dark:bg-slate-800 cursor-pointer"
              >
                <option value="ALL">All Statuses</option>
                <option value="draft">Draft</option>
                <option value="validating">Validating</option>
                <option value="validated">Validated</option>
                <option value="submitted">Submitted</option>
                <option value="accepted">Accepted</option>
                <option value="rejected">Rejected</option>
                <option value="partial">Partial Accept</option>
                <option value="error">Error</option>
              </select>
            </div>
          </div>

          {/* Loading / error / data state */}
          {batchesQuery.isLoading ? (
            <div className="p-4 flex flex-col gap-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="h-[52px] rounded-lg bg-slate-100 dark:bg-slate-800" aria-hidden="true" />
              ))}
            </div>
          ) : batchesQuery.isError ? (
            <div className="p-12 text-center text-slate-400 dark:text-slate-500">
              <AlertCircle size={32} className="text-red-500 dark:text-red-400 mb-3 opacity-60 mx-auto" />
              <p className="text-sm font-semibold text-slate-600 dark:text-slate-300 mb-1">
                Could not load submission batches
              </p>
              <p className="text-[13px] text-slate-400 dark:text-slate-500 mb-4">
                Check your connection and try again.
              </p>
              <button
                onClick={() => batchesQuery.refetch()}
                className="px-5 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 font-semibold text-[13px] cursor-pointer"
              >
                Retry
              </button>
            </div>
          ) : (
            <BatchesTable
              batches={batches}
              expandedId={expandedBatch}
              onExpand={setExpandedBatch}
              onValidate={handleValidate}
              onDownload={handleDownload}
              onUploadResponse={(id, name) => setUploadTarget({ id, name })}
              onViewErrors={handleViewErrors}
            />
          )}
        </div>
      </div>

      {showGenerate && (
        <LazyGenerateDialog
          onClose={() => setShowGenerate(false)}
          onSuccess={() => {
            queryClient.invalidateQueries({ queryKey: ["submissions-batches"] });
            queryClient.invalidateQueries({ queryKey: ["submissions-stats"] });
          }}
        />
      )}

      {uploadTarget && (
        <LazyUploadResponseDialog
          batchId={uploadTarget.id}
          batchName={uploadTarget.name}
          onClose={() => setUploadTarget(null)}
          onSuccess={() => {
            queryClient.invalidateQueries({ queryKey: ["submission-batch-detail", uploadTarget.id] });
          }}
        />
      )}
    </div>
  );
}
