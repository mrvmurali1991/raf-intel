"use client";

/**
 * SubmissionsDialogsPanels — lazy-loaded heavy overlays for submissions page.
 * Extracted to defer modal + detail panel JS from initial paint.
 * Exports: GenerateDialog, UploadResponseDialog, BatchDetailPanel
 */

import React, { useState, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import {
  Send,
  AlertCircle,
  X,
  Loader2,
  Play,
  Upload,
  FileCheck,
  CheckCircle,
  FileText,
  List,
  ShieldCheck,
  Inbox,
  DollarSign,
  XCircle,
  AlertTriangle,
} from "lucide-react";

// ─────────────────────────────────────────────
// Local types
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

// ─────────────────────────────────────────────
// Local API
// ─────────────────────────────────────────────

async function fetchBatchDetail(batchId: string): Promise<BatchDetail> {
  const { data } = await api.get(`/api/submissions/batches/${batchId}`);
  return data;
}

// ─────────────────────────────────────────────
// Local badge helpers
// ─────────────────────────────────────────────

function StatusBadge({ status }: { status: BatchStatus }) {
  const map: Record<BatchStatus, { label: string; cls: string; dotCls: string; icon: React.ReactNode }> = {
    draft:      { label: "Draft",          cls: "bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300",           dotCls: "bg-slate-400",          icon: null },
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
// GenerateDialog
// ─────────────────────────────────────────────

export interface GenerateDialogProps {
  onClose: () => void;
  onSuccess: () => void;
}

export function GenerateDialog({ onClose, onSuccess }: GenerateDialogProps) {
  const [submissionType, setSubmissionType] = useState<SubmissionType>("RAPS");
  const [paymentYear, setPaymentYear] = useState<number>(new Date().getFullYear());
  const [sweepType, setSweepType] = useState<SweepType>("Initial");
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [progressLabel, setProgressLabel] = useState("");

  const currentYear = new Date().getFullYear();
  const years = [currentYear - 1, currentYear, currentYear + 1];

  async function handleGenerate() {
    setGenerating(true);
    setGenerateError(null);
    const steps = [
      { label: "Extracting encounter records…", pct: 20 },
      { label: "Mapping ICD-10 to HCC codes…", pct: 45 },
      { label: "Running validation rules…", pct: 70 },
      { label: "Building submission file…", pct: 90 },
      { label: "Complete", pct: 100 },
    ];
    for (const step of steps) {
      setProgressLabel(step.label);
      setProgress(step.pct);
      await new Promise((r) => setTimeout(r, 700));
    }
    try {
      await api.post(`/api/submissions/generate`, {
        submission_type: submissionType,
        payment_year: paymentYear,
        sweep_type: sweepType,
      });
      onSuccess();
      onClose();
    } catch (err: any) {
      const msg =
        err?.response?.data?.detail ??
        err?.response?.data?.message ??
        err?.message ??
        "Failed to generate submission. Please try again.";
      setGenerateError(msg);
      setGenerating(false);
      setProgress(0);
      setProgressLabel("");
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[100] p-4"
      role="dialog" aria-modal="true" aria-labelledby="gen-dialog-title">
      <div className="bg-white dark:bg-slate-800 rounded-[14px] w-full max-w-[480px] shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-[18px] border-b border-slate-200 dark:border-slate-700">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-[10px] bg-blue-600/10 flex items-center justify-center text-blue-600 dark:text-blue-400">
              <Send size={18} />
            </div>
            <div>
              <h2 id="gen-dialog-title" className="m-0 text-base font-bold text-slate-900 dark:text-slate-50">Generate Submission</h2>
              <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">Create a new CMS submission batch</p>
            </div>
          </div>
          <button onClick={onClose} disabled={generating} aria-label="Close dialog"
            className="bg-transparent border border-slate-200 dark:border-slate-700 rounded-lg w-8 h-8 flex items-center justify-center text-slate-500 dark:text-slate-400 disabled:cursor-not-allowed cursor-pointer">
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 flex flex-col gap-4">
          {/* Submission Type */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-slate-700 dark:text-slate-200">Submission Type</label>
            <div className="flex gap-2">
              {(["RAPS", "EDPS"] as SubmissionType[]).map((t) => (
                <button key={t} onClick={() => setSubmissionType(t)} disabled={generating}
                  className={`flex-1 px-4 py-2.5 rounded-lg font-bold text-sm transition-all disabled:cursor-not-allowed cursor-pointer border-2 ${
                    submissionType === t
                      ? "border-blue-600 bg-blue-50 dark:bg-blue-950 text-blue-700 dark:text-blue-300"
                      : "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300"
                  }`}>
                  {t}
                </button>
              ))}
            </div>
          </div>

          {/* Payment Year */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-slate-700 dark:text-slate-200">Payment Year</label>
            <select value={paymentYear} onChange={(e) => setPaymentYear(Number(e.target.value))} disabled={generating}
              className="px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 text-sm text-slate-800 dark:text-slate-100 bg-white dark:bg-slate-800 disabled:cursor-not-allowed cursor-pointer">
              {years.map((y) => <option key={y} value={y}>PY{y}</option>)}
            </select>
          </div>

          {/* Sweep Type */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-slate-700 dark:text-slate-200">Sweep Type</label>
            <div className="grid grid-cols-2 gap-2">
              {(["Initial", "Mid-Year", "Final", "Supplemental"] as SweepType[]).map((s) => (
                <button key={s} onClick={() => setSweepType(s)} disabled={generating}
                  className={`px-3 py-2 rounded-lg font-semibold text-[13px] transition-all disabled:cursor-not-allowed cursor-pointer border-2 ${
                    sweepType === s
                      ? "border-blue-600 bg-blue-50 dark:bg-blue-950 text-blue-700 dark:text-blue-300"
                      : "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300"
                  }`}>
                  {s}
                </button>
              ))}
            </div>
          </div>

          {/* Error */}
          {generateError && (
            <div className="bg-red-50 dark:bg-red-950 border border-red-500/40 rounded-lg px-3.5 py-3 flex items-start gap-2" role="alert">
              <AlertCircle size={15} className="text-destructive shrink-0 mt-px" />
              <span className="text-[13px] text-red-600 dark:text-red-400">{generateError}</span>
            </div>
          )}

          {/* Progress */}
          {generating && (
            <div className="bg-blue-50 dark:bg-blue-950 rounded-[10px] px-4 py-3.5 flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <Loader2 size={14} className="text-blue-600 dark:text-blue-400 animate-spin" />
                <span className="text-[13px] font-semibold text-blue-700 dark:text-blue-300">{progressLabel}</span>
                <span className="ml-auto text-xs font-bold text-blue-700 dark:text-blue-300">{progress}%</span>
              </div>
              <div className="h-1.5 rounded-sm bg-blue-600/10 overflow-hidden">
                <div className="h-full rounded-sm bg-blue-600 transition-[width] duration-400" style={{ width: `${progress}%` }} />
              </div>
            </div>
          )}

          {/* Generate Button */}
          <button onClick={handleGenerate} disabled={generating}
            className={`w-full px-5 py-3 rounded-[10px] border-none text-white font-bold text-sm flex items-center justify-center gap-2 ${
              generating ? "bg-slate-300 dark:bg-slate-600 cursor-not-allowed" : "sub-gradient-btn cursor-pointer"
            }`}>
            {generating ? (
              <><Loader2 size={16} className="animate-spin" />Generating…</>
            ) : (
              <><Play size={16} />Generate &amp; Validate</>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
// UploadResponseDialog
// ─────────────────────────────────────────────

export interface UploadResponseDialogProps {
  batchId: string;
  batchName: string;
  onClose: () => void;
  onSuccess: () => void;
}

export function UploadResponseDialog({ batchId, batchName, onClose, onSuccess }: UploadResponseDialogProps) {
  const [file, setFile] = useState<File | null>(null);
  const [fileType, setFileType] = useState<"MAO-002" | "MAO-004">("MAO-002");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [parsed, setParsed] = useState<{ accepted: number; rejected: number; total: number } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  function handleFile(f: File) { setFile(f); setParsed(null); }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault(); setDragOver(false);
    if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
  }

  async function handleUpload() {
    if (!file) return;
    setUploading(true); setUploadError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("file_type", fileType);
      const { data } = await api.post(`/api/submissions/batches/${batchId}/responses`, form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setParsed({
        accepted: data?.accepted ?? data?.accepted_records ?? 0,
        rejected: data?.rejected ?? data?.rejected_records ?? 0,
        total:    data?.total    ?? data?.records_parsed   ?? 0,
      });
    } catch (err: any) {
      const msg = err?.response?.data?.detail ?? err?.response?.data?.message ?? err?.message ?? "Failed to upload response file. Please try again.";
      setUploadError(msg);
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[100] p-4"
      role="dialog" aria-modal="true" aria-labelledby="upload-dialog-title">
      <div className="bg-white dark:bg-slate-800 rounded-[14px] w-full max-w-[460px] shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-[18px] border-b border-slate-200 dark:border-slate-700">
          <div>
            <h2 id="upload-dialog-title" className="m-0 text-base font-bold text-slate-900 dark:text-slate-50">Upload CMS Response</h2>
            <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{batchName}</p>
          </div>
          <button onClick={onClose} aria-label="Close dialog"
            className="bg-transparent border border-slate-200 dark:border-slate-700 rounded-lg w-8 h-8 cursor-pointer flex items-center justify-center text-slate-500 dark:text-slate-400">
            <X size={16} />
          </button>
        </div>

        <div className="px-6 py-5 flex flex-col gap-4">
          {/* File type selector */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-slate-700 dark:text-slate-200">Response File Type</label>
            <div className="flex gap-2">
              {(["MAO-002", "MAO-004"] as const).map((t) => (
                <button key={t} onClick={() => setFileType(t)} disabled={uploading}
                  className={`flex-1 px-3 py-2 rounded-lg font-bold text-[13px] transition-all disabled:cursor-not-allowed cursor-pointer border-2 ${
                    fileType === t
                      ? "border-blue-600 bg-blue-50 dark:bg-blue-950 text-blue-700 dark:text-blue-300"
                      : "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300"
                  }`}>
                  {t}
                </button>
              ))}
            </div>
            <p className="m-0 text-[11px] text-slate-400 dark:text-slate-500">
              {fileType === "MAO-002" ? "MAO-002: CMS acknowledgement of receipt (RAPS)" : "MAO-004: CMS transaction error report"}
            </p>
          </div>

          {/* Drop zone */}
          <div onDrop={handleDrop} onDragOver={(e) => { e.preventDefault(); setDragOver(true); }} onDragLeave={() => setDragOver(false)}
            onClick={() => !uploading && inputRef.current?.click()}
            className={`border-2 border-dashed rounded-[10px] px-5 py-7 text-center transition-all ${
              uploading ? "cursor-not-allowed" : "cursor-pointer"
            } ${
              dragOver ? "border-blue-500 bg-blue-50 dark:bg-blue-950"
              : file ? "border-emerald-500 bg-emerald-50 dark:bg-emerald-950"
              : "border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-800"
            }`}>
            <input ref={inputRef} type="file" accept=".txt,.dat" className="hidden" onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])} />
            {file ? (
              <div className="flex flex-col items-center gap-1.5">
                <FileCheck size={28} className="text-emerald-600 dark:text-emerald-400" />
                <span className="text-sm font-semibold text-slate-800 dark:text-slate-100">{file.name}</span>
                <span className="text-xs text-slate-500 dark:text-slate-400">{(file.size / 1024).toFixed(1)} KB</span>
                {!uploading && (
                  <button onClick={(e) => { e.stopPropagation(); setFile(null); setParsed(null); }}
                    className="text-[11px] text-slate-500 dark:text-slate-400 bg-transparent border-none cursor-pointer underline">
                    Remove
                  </button>
                )}
              </div>
            ) : (
              <div className="flex flex-col items-center gap-1.5">
                <Upload size={28} className="text-muted-foreground" />
                <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">Drop response file here</span>
                <span className="text-xs text-slate-500 dark:text-slate-400">or click to browse — .txt, .dat</span>
              </div>
            )}
          </div>

          {/* Upload error */}
          {uploadError && (
            <div className="bg-red-50 dark:bg-red-950 border border-red-500/40 rounded-lg px-3.5 py-3 flex items-start gap-2" role="alert">
              <AlertCircle size={15} className="text-destructive shrink-0 mt-px" />
              <span className="text-[13px] text-red-600 dark:text-red-400">{uploadError}</span>
            </div>
          )}

          {/* Parsed results */}
          {parsed && (
            <div className="bg-emerald-50 dark:bg-emerald-950 border border-emerald-500/20 rounded-[10px] px-4 py-3.5">
              <div className="flex items-center gap-1.5 mb-2.5">
                <CheckCircle size={15} className="text-emerald-600 dark:text-emerald-400" />
                <span className="text-[13px] font-bold text-emerald-600 dark:text-emerald-400">File parsed successfully</span>
              </div>
              <div className="flex gap-5">
                <div>
                  <div className="text-lg font-extrabold text-slate-900 dark:text-slate-50">{parsed.total?.toLocaleString() ?? "0"}</div>
                  <div className="text-[11px] text-slate-500 dark:text-slate-400">Total Records</div>
                </div>
                <div>
                  <div className="text-lg font-extrabold text-emerald-600 dark:text-emerald-400">{parsed.accepted?.toLocaleString() ?? "0"}</div>
                  <div className="text-[11px] text-slate-500 dark:text-slate-400">Accepted</div>
                </div>
                <div>
                  <div className="text-lg font-extrabold text-red-600 dark:text-red-400">{parsed.rejected?.toLocaleString() ?? "0"}</div>
                  <div className="text-[11px] text-slate-500 dark:text-slate-400">Rejected</div>
                </div>
              </div>
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-2">
            <button onClick={onClose}
              className="flex-1 py-2.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 font-semibold text-[13px] cursor-pointer">
              {parsed ? "Close" : "Cancel"}
            </button>
            {!parsed && (
              <button onClick={handleUpload} disabled={!file || uploading}
                className={`flex-[2] py-2.5 rounded-lg border-none text-white font-bold text-[13px] flex items-center justify-center gap-1.5 ${
                  !file || uploading ? "bg-slate-300 dark:bg-slate-600 cursor-not-allowed" : "sub-gradient-btn cursor-pointer"
                }`}>
                {uploading ? (
                  <><Loader2 size={14} className="animate-spin" />Parsing…</>
                ) : (
                  <><Upload size={14} />Upload &amp; Parse</>
                )}
              </button>
            )}
            {parsed && (
              <button onClick={() => { onSuccess(); onClose(); }}
                className="flex-[2] py-2.5 rounded-lg border-none bg-emerald-600 text-white font-bold text-[13px] cursor-pointer flex items-center justify-center gap-1.5">
                <CheckCircle size={14} />Save Results
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
// BatchDetailPanel
// ─────────────────────────────────────────────

export interface BatchDetailPanelProps {
  batchId: string;
  onClose: () => void;
  onUploadResponse: (batchId: string, batchName: string) => void;
}

export function BatchDetailPanel({ batchId, onClose, onUploadResponse }: BatchDetailPanelProps) {
  const [tab, setTab] = useState<DetailTab>("records");
  const [recordPage, setRecordPage] = useState(0);
  const PAGE = 10;

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["submission-batch-detail", batchId],
    queryFn: () => fetchBatchDetail(batchId),
  });

  const tabs: { key: DetailTab; label: string; icon: React.ReactNode }[] = [
    { key: "records",        label: "Records",        icon: <List size={13} /> },
    { key: "validation",     label: "Validation",     icon: <ShieldCheck size={13} /> },
    { key: "responses",      label: "Responses",      icon: <Inbox size={13} /> },
    { key: "reconciliation", label: "Reconciliation", icon: <DollarSign size={13} /> },
  ];

  return (
    <div className="premium-card animate-fade-in overflow-hidden mt-4">
      {/* Panel header */}
      <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800">
        <div className="flex items-center gap-2.5">
          <FileText size={16} className="text-blue-600 dark:text-blue-400" />
          <span className="text-sm font-bold text-slate-900 dark:text-slate-50">Batch {data?.batch.batch_id ?? batchId}</span>
          {data && <StatusBadge status={data.batch.status} />}
          {data && <TypeBadge type={data.batch.submission_type} />}
        </div>
        <button onClick={onClose} aria-label="Close detail panel"
          className="w-7 h-7 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 cursor-pointer flex items-center justify-center text-slate-500 dark:text-slate-400">
          <X size={14} />
        </button>
      </div>

      {/* Tab strip */}
      <div className="flex gap-0 border-b border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 overflow-x-auto">
        {tabs.map((t) => {
          const active = tab === t.key;
          return (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`inline-flex items-center gap-[5px] px-[18px] py-[11px] text-[13px] bg-transparent border-none cursor-pointer whitespace-nowrap transition-colors border-b-2 ${
                active
                  ? "font-bold text-blue-600 dark:text-blue-400 border-blue-600 dark:border-blue-400"
                  : "font-medium text-slate-500 dark:text-slate-400 border-transparent"
              }`}>
              {t.icon}{t.label}
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      {isLoading ? (
        <div className="flex items-center justify-center p-12 gap-2.5 text-slate-400 dark:text-slate-500">
          <Loader2 size={20} className="animate-spin" />
          <span className="text-sm">Loading batch detail…</span>
        </div>
      ) : isError ? (
        <div className="m-5 px-4 py-3.5 rounded-[10px] border border-red-500/40 bg-red-50 dark:bg-red-950 flex items-center justify-between gap-3" role="alert">
          <div className="flex items-center gap-2">
            <AlertCircle size={16} className="text-red-600 dark:text-red-400 shrink-0" />
            <span className="text-[13px] font-semibold text-red-600 dark:text-red-400">
              {(error as any)?.response?.data?.detail ?? (error as any)?.message ?? "Failed to load batch detail."}
            </span>
          </div>
          <button onClick={() => refetch()}
            className="px-3 py-[5px] rounded-md border border-red-500/40 bg-white dark:bg-slate-800 text-red-600 dark:text-red-400 font-semibold text-xs cursor-pointer shrink-0">
            Retry
          </button>
        </div>
      ) : !data ? null : (
        <div>
          {/* ── RECORDS TAB ── */}
          {tab === "records" && (
            <>
              <div className="overflow-x-auto">
                <table className="w-full border-collapse" style={{ minWidth: 860 }}>
                  <thead>
                    <tr>
                      {["Patient", "ICD-10", "HCC", "DOS", "Through Date", "Provider NPI", "Validation", "CMS Status"].map(h => (
                        <th key={h} className="px-3 py-2 text-[11px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-widest text-left border-b-2 border-slate-200 dark:border-slate-700 bg-gradient-to-b from-slate-50 dark:from-slate-800 to-white dark:to-slate-900 whitespace-nowrap">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(data.records ?? []).slice(recordPage * PAGE, (recordPage + 1) * PAGE).map((r) => (
                      <tr key={r.id} className="transition-colors">
                        <td className="px-3 py-[11px] text-xs text-slate-700 dark:text-slate-200 border-b border-slate-100 dark:border-slate-800 align-middle">
                          <div className="font-semibold text-slate-800 dark:text-slate-100 text-xs">{r.patient_name}</div>
                          <div className="text-[10px] text-slate-400 dark:text-slate-500 font-mono">{r.patient_id}</div>
                        </td>
                        <td className="px-3 py-[11px] text-xs text-slate-700 dark:text-slate-200 border-b border-slate-100 dark:border-slate-800 align-middle">
                          <span className="font-mono text-xs font-bold text-blue-700 dark:text-blue-300 bg-blue-50 dark:bg-blue-950 px-1.5 py-[2px] rounded">
                            {r.icd10_code}
                          </span>
                        </td>
                        <td className="px-3 py-[11px] text-xs text-slate-700 dark:text-slate-200 border-b border-slate-100 dark:border-slate-800 align-middle">
                          {r.hcc_code ? (
                            <div>
                              <span className="font-bold text-violet-600 dark:text-violet-400 text-xs">HCC{r.hcc_code}</span>
                              <div className="text-[10px] text-slate-400 dark:text-slate-500 max-w-[140px] overflow-hidden text-ellipsis whitespace-nowrap">{r.hcc_description}</div>
                            </div>
                          ) : (
                            <span className="text-slate-400 dark:text-slate-500 text-xs">—</span>
                          )}
                        </td>
                        <td className="px-3 py-[11px] text-xs font-mono text-slate-600 dark:text-slate-300 border-b border-slate-100 dark:border-slate-800 align-middle">{r.date_of_service}</td>
                        <td className="px-3 py-[11px] text-xs font-mono text-slate-600 dark:text-slate-300 border-b border-slate-100 dark:border-slate-800 align-middle">{r.through_date}</td>
                        <td className="px-3 py-[11px] text-[11px] font-mono text-slate-500 dark:text-slate-400 border-b border-slate-100 dark:border-slate-800 align-middle">{r.provider_id}</td>
                        <td className="px-3 py-[11px] text-xs text-slate-700 dark:text-slate-200 border-b border-slate-100 dark:border-slate-800 align-middle"><ValidationBadge status={r.validation_status} /></td>
                        <td className="px-3 py-[11px] text-xs text-slate-700 dark:text-slate-200 border-b border-slate-100 dark:border-slate-800 align-middle">
                          <div>
                            <CmsStatusBadge status={r.cms_status} />
                            {r.rejection_reason && (
                              <div className="text-[10px] text-red-500 dark:text-red-400 mt-[3px] max-w-[140px]">{r.rejection_reason}</div>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {/* Pagination */}
              <div className="flex items-center justify-between px-4 py-3 border-t border-slate-100 dark:border-slate-800">
                <span className="text-xs text-slate-500 dark:text-slate-400">
                  Showing {recordPage * PAGE + 1}–{Math.min((recordPage + 1) * PAGE, (data.records ?? []).length)} of {(data.records ?? []).length}
                </span>
                <div className="flex gap-1.5">
                  <button onClick={() => setRecordPage((p) => Math.max(0, p - 1))} disabled={recordPage === 0}
                    className="px-3 py-1 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs disabled:text-slate-300 dark:disabled:text-slate-600 text-slate-600 dark:text-slate-300 disabled:cursor-not-allowed cursor-pointer">
                    Prev
                  </button>
                  <button onClick={() => setRecordPage((p) => p + 1)} disabled={(recordPage + 1) * PAGE >= (data.records ?? []).length}
                    className="px-3 py-1 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs disabled:text-slate-300 dark:disabled:text-slate-600 text-slate-600 dark:text-slate-300 disabled:cursor-not-allowed cursor-pointer">
                    Next
                  </button>
                </div>
              </div>
            </>
          )}

          {/* ── VALIDATION TAB ── */}
          {tab === "validation" && (
            <div className="p-5">
              <div className="flex gap-3 mb-5">
                <div className="flex-1 bg-red-50 dark:bg-red-950 border border-red-500/20 rounded-[10px] px-4 py-3.5 flex items-center gap-3">
                  <XCircle size={24} className="text-red-600 dark:text-red-400 shrink-0" />
                  <div>
                    <div className="text-[22px] font-extrabold text-red-600 dark:text-red-400">
                      {(data.validation_issues ?? []).filter((i) => i.severity === "error").reduce((s, i) => s + i.count, 0)}
                    </div>
                    <div className="text-xs text-red-500 dark:text-red-400 font-semibold">Errors</div>
                  </div>
                </div>
                <div className="flex-1 bg-amber-50 dark:bg-amber-950 border border-amber-500/20 rounded-[10px] px-4 py-3.5 flex items-center gap-3">
                  <AlertTriangle size={24} className="text-amber-600 dark:text-amber-400 shrink-0" />
                  <div>
                    <div className="text-[22px] font-extrabold text-amber-600 dark:text-amber-400">
                      {(data.validation_issues ?? []).filter((i) => i.severity === "warning").reduce((s, i) => s + i.count, 0)}
                    </div>
                    <div className="text-xs text-amber-500 dark:text-amber-400 font-semibold">Warnings</div>
                  </div>
                </div>
              </div>
              {(data.validation_issues ?? []).length === 0 ? (
                <div className="p-10 text-center text-slate-400 dark:text-slate-500 border-2 border-dashed border-slate-200 dark:border-slate-700 rounded-[10px]">
                  <CheckCircle size={28} className="text-emerald-500 dark:text-emerald-400 mb-2 opacity-70 mx-auto" />
                  <p className="m-0 text-sm font-medium text-emerald-600 dark:text-emerald-400">No validation issues found</p>
                </div>
              ) : (
                <div className="flex flex-col gap-2.5">
                  {(data.validation_issues ?? []).map((issue) => (
                    <div key={issue.rule_id} className={`hover-lift rounded-lg px-4 py-3.5 border-l-4 border ${
                      issue.severity === "error"
                        ? "border-red-500/20 border-l-red-500 bg-red-50 dark:bg-red-950"
                        : "border-amber-500/20 border-l-amber-500 bg-amber-50 dark:bg-amber-950"
                    }`}>
                      <div className="flex items-center justify-between mb-1.5">
                        <div className="flex items-center gap-2">
                          {issue.severity === "error" ? <XCircle size={14} className="text-red-600 dark:text-red-400" /> : <AlertTriangle size={14} className="text-amber-600 dark:text-amber-400" />}
                          <span className="text-[13px] font-bold text-slate-800 dark:text-slate-100">{issue.rule_name}</span>
                          <span className="text-[10px] text-slate-500 dark:text-slate-400 font-mono">{issue.rule_id}</span>
                        </div>
                        <span className={`text-xs font-bold ${issue.severity === "error" ? "text-red-600 dark:text-red-400" : "text-amber-600 dark:text-amber-400"}`}>{issue.count} affected</span>
                      </div>
                      <p className="m-0 mb-1.5 text-xs text-slate-600 dark:text-slate-300">{issue.description}</p>
                      <div className="flex items-start gap-1.5 bg-white/60 dark:bg-slate-800/60 rounded-md px-2.5 py-2">
                        <CheckCircle size={12} className="text-emerald-600 dark:text-emerald-400 shrink-0 mt-px" />
                        <span className="text-xs text-slate-700 dark:text-slate-200">{issue.recommendation}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ── RESPONSES TAB ── */}
          {tab === "responses" && (
            <div className="p-5">
              <div className="flex items-center justify-between mb-4">
                <span className="text-sm font-bold text-slate-800 dark:text-slate-100">Uploaded Response Files</span>
                <button onClick={() => onUploadResponse(data.batch.id, data.batch.batch_id)}
                  className="sub-gradient-btn flex items-center gap-1.5 px-3.5 py-[7px] rounded-lg border-none text-white font-semibold text-xs cursor-pointer">
                  <Upload size={13} />Upload Response
                </button>
              </div>
              {(data.response_files ?? []).length === 0 ? (
                <div className="p-10 text-center text-slate-400 dark:text-slate-500 border-2 border-dashed border-slate-200 dark:border-slate-700 rounded-[10px]">
                  <Inbox size={32} className="mb-2 opacity-50 mx-auto" />
                  <p className="m-0 text-sm font-medium">No response files uploaded yet</p>
                </div>
              ) : (
                <div className="flex flex-col gap-2.5">
                  {(data.response_files ?? []).map((rf) => (
                    <div key={rf.id} className="hover-lift border border-slate-200 dark:border-slate-700 rounded-[10px] px-4 py-3.5 bg-white dark:bg-slate-800 flex items-center gap-4">
                      <div className="w-10 h-10 rounded-[10px] bg-blue-50 dark:bg-blue-950 flex items-center justify-center shrink-0 text-blue-600 dark:text-blue-400">
                        <FileText size={18} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="font-semibold text-[13px] text-slate-800 dark:text-slate-100">{rf.file_name}</div>
                        <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">{rf.file_type} · Uploaded {new Date(rf.uploaded_at).toLocaleDateString()}</div>
                      </div>
                      <div className="flex gap-5 text-center">
                        <div>
                          <div className="text-base font-extrabold text-slate-900 dark:text-slate-50">{rf.records_parsed?.toLocaleString() ?? "0"}</div>
                          <div className="text-[10px] text-slate-400 dark:text-slate-500">Parsed</div>
                        </div>
                        <div>
                          <div className="text-base font-extrabold text-emerald-600 dark:text-emerald-400">{rf.accepted?.toLocaleString() ?? "0"}</div>
                          <div className="text-[10px] text-slate-400 dark:text-slate-500">Accepted</div>
                        </div>
                        <div>
                          <div className="text-base font-extrabold text-red-600 dark:text-red-400">{rf.rejected?.toLocaleString() ?? "0"}</div>
                          <div className="text-[10px] text-slate-400 dark:text-slate-500">Rejected</div>
                        </div>
                      </div>
                      <span className={`px-2 py-[3px] rounded text-[11px] font-semibold shrink-0 ${
                        rf.status === "parsed"
                          ? "bg-emerald-50 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400"
                          : "bg-amber-50 dark:bg-amber-950 text-amber-600 dark:text-amber-400"
                      }`}>
                        {rf.status === "parsed" ? "Parsed" : "Processing"}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ── RECONCILIATION TAB ── */}
          {tab === "reconciliation" && (
            <div className="p-5">
              <div className="flex gap-3 mb-5">
                <div className="flex-1 bg-emerald-50 dark:bg-emerald-950 border border-emerald-500/20 rounded-[10px] px-4 py-3.5">
                  <div className="text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1.5">Total Payment Impact</div>
                  <div className="text-2xl font-extrabold text-emerald-600 dark:text-emerald-400">${data.total_payment_impact?.toLocaleString() ?? "0"}</div>
                </div>
                <div className="flex-1 bg-blue-50 dark:bg-blue-950 border border-blue-500/20 rounded-[10px] px-4 py-3.5">
                  <div className="text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1.5">Risk Score Adjustment</div>
                  <div className="text-2xl font-extrabold text-blue-700 dark:text-blue-300">+{(data.risk_score_adjustment ?? 0).toFixed(3)}</div>
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full border-collapse">
                  <thead>
                    <tr>
                      {["HCC", "Description"].map(h => (
                        <th key={h} className="px-3 py-2 text-[11px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-widest text-left border-b-2 border-slate-200 dark:border-slate-700 bg-gradient-to-b from-slate-50 dark:from-slate-800 to-white dark:to-slate-900 whitespace-nowrap">{h}</th>
                      ))}
                      {["Patients", "Risk Score Delta", "Payment Impact"].map(h => (
                        <th key={h} className="px-3 py-2 text-[11px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-widest text-right border-b-2 border-slate-200 dark:border-slate-700 bg-gradient-to-b from-slate-50 dark:from-slate-800 to-white dark:to-slate-900 whitespace-nowrap">{h}</th>
                      ))}
                      <th className="px-3 py-2 text-[11px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-widest text-left border-b-2 border-slate-200 dark:border-slate-700 bg-gradient-to-b from-slate-50 dark:from-slate-800 to-white dark:to-slate-900 whitespace-nowrap">CMS Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data.reconciliation ?? []).map((r) => (
                      <tr key={r.hcc_code}>
                        <td className="px-3 py-[11px] text-xs text-slate-700 dark:text-slate-200 border-b border-slate-100 dark:border-slate-800 align-middle">
                          <span className="font-bold text-violet-600 dark:text-violet-400 font-mono">HCC{r.hcc_code}</span>
                        </td>
                        <td className="px-3 py-[11px] text-xs text-slate-700 dark:text-slate-200 border-b border-slate-100 dark:border-slate-800 align-middle max-w-[200px]">
                          <span className="text-xs text-slate-700 dark:text-slate-200">{r.hcc_description}</span>
                        </td>
                        <td className="px-3 py-[11px] text-xs text-slate-700 dark:text-slate-200 border-b border-slate-100 dark:border-slate-800 align-middle text-right font-semibold">{r.patient_count}</td>
                        <td className="px-3 py-[11px] text-xs border-b border-slate-100 dark:border-slate-800 align-middle text-right">
                          <span className="font-bold text-blue-700 dark:text-blue-300 font-mono">+{(r.risk_score_delta ?? 0).toFixed(3)}</span>
                        </td>
                        <td className="px-3 py-[11px] text-xs border-b border-slate-100 dark:border-slate-800 align-middle text-right">
                          <span className="font-bold text-emerald-600 dark:text-emerald-400 font-mono">${r.payment_delta?.toLocaleString() ?? "0"}</span>
                        </td>
                        <td className="px-3 py-[11px] text-xs text-slate-700 dark:text-slate-200 border-b border-slate-100 dark:border-slate-800 align-middle"><CmsStatusBadge status={r.cms_status} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
