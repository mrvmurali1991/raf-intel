"use client";

/**
 * SubmissionsDialogsPanels — lazy-loaded heavy overlays for submissions page.
 * Extracted to defer modal + detail panel JS from initial paint.
 * Exports: GenerateDialog, UploadResponseDialog, BatchDetailPanel
 */

import React, { useState, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { tokens } from "@/styles/tokens";
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
// Local design tokens
// ─────────────────────────────────────────────

const T = {
  white:      tokens.white,
  slate50:    tokens.slate50,
  slate100:   tokens.slate100,
  slate200:   tokens.slate200,
  slate300:   tokens.slate300,
  slate400:   tokens.slate400,
  slate500:   tokens.slate500,
  slate600:   tokens.slate600,
  slate700:   tokens.slate700,
  slate800:   tokens.slate800,
  slate900:   tokens.slate900,
  blue50:     tokens.primarySoft,
  blue100:    "rgba(37,99,235,0.12)",
  blue500:    tokens.infoBlue,
  blue600:    tokens.primary,
  blue700:    tokens.primaryDark,
  emerald50:  tokens.successSoft,
  emerald100: tokens.emerald100,
  emerald500: tokens.success,
  emerald600: tokens.riskLow,
  amber50:    tokens.warningSoft,
  amber100:   tokens.warningSoft,
  amber500:   tokens.warningStrong,
  amber600:   tokens.riskMedium,
  red50:      tokens.riskHighSoft,
  red100:     tokens.dangerSoft,
  red500:     tokens.riskHigh,
  red600:     tokens.danger,
  violet50:   "rgba(139,92,246,0.08)",
  violet500:  tokens.accentPurple,
  violet600:  "rgba(124,58,237,1)",
  gray100:    tokens.slate100,
  gray200:    tokens.slate200,
  gray400:    tokens.slate400,
  gray500:    tokens.slate500,
};

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
// Local badge helpers (needed inside this file)
// ─────────────────────────────────────────────

function StatusBadge({ status }: { status: BatchStatus }) {
  const map: Record<BatchStatus, { label: string; bg: string; color: string; dot: string; icon: React.ReactNode }> = {
    draft:      { label: "Draft",         bg: T.slate100,           color: T.slate600,  dot: T.slate400,  icon: null },
    validating: { label: "Validating",    bg: T.blue100,            color: T.blue700,   dot: T.blue500,   icon: <Loader2 size={11} style={{ animation: "spin 1s linear infinite" }} /> },
    validated:  { label: "Validated",     bg: T.emerald50,          color: T.emerald600, dot: T.emerald500, icon: <CheckCircle size={11} /> },
    submitted:  { label: "Submitted",     bg: `${T.emerald500}18`,  color: T.emerald600, dot: T.emerald500, icon: <Send size={11} /> },
    accepted:   { label: "Accepted",      bg: T.emerald100,         color: T.emerald600, dot: T.emerald500, icon: <CheckCircle size={11} /> },
    rejected:   { label: "Rejected",      bg: T.red100,             color: T.red600,    dot: T.red500,    icon: <XCircle size={11} /> },
    partial:    { label: "Partial Accept",bg: T.amber100,           color: T.amber600,  dot: T.amber500,  icon: <AlertCircle size={11} /> },
    error:      { label: "Error",         bg: T.red50,              color: T.red500,    dot: T.red500,    icon: <XCircle size={11} /> },
  };
  const cfg = map[status] ?? { label: status, bg: T.gray100, color: T.gray500, dot: T.gray400, icon: null };
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "4px 10px", borderRadius: 999, fontSize: 11, fontWeight: 600, backgroundColor: cfg.bg, color: cfg.color, whiteSpace: "nowrap", border: `1px solid ${cfg.color}20` }}>
      <span style={{ width: 7, height: 7, borderRadius: "50%", backgroundColor: cfg.dot, boxShadow: `0 0 6px ${cfg.dot}60`, flexShrink: 0 }} />
      {cfg.icon}
      {cfg.label}
    </span>
  );
}

function TypeBadge({ type }: { type: SubmissionType }) {
  const isRAPS = type === "RAPS";
  return (
    <span style={{ display: "inline-flex", alignItems: "center", padding: "3px 9px", borderRadius: 6, fontSize: 11, fontWeight: 700, backgroundColor: isRAPS ? T.violet50 : T.blue50, color: isRAPS ? T.violet600 : T.blue700, border: `1px solid ${isRAPS ? T.violet500 + "33" : T.blue500 + "33"}`, letterSpacing: "0.04em" }}>
      {type}
    </span>
  );
}

function ValidationBadge({ status }: { status: "pass" | "warning" | "error" }) {
  const map = {
    pass:    { label: "Pass",    bg: T.emerald50, color: T.emerald600 },
    warning: { label: "Warning", bg: T.amber50,   color: T.amber600 },
    error:   { label: "Error",   bg: T.red50,     color: T.red500 },
  };
  const cfg = map[status];
  return (
    <span style={{ padding: "2px 7px", borderRadius: 4, fontSize: 11, fontWeight: 600, backgroundColor: cfg.bg, color: cfg.color }}>
      {cfg.label}
    </span>
  );
}

function CmsStatusBadge({ status }: { status: "accepted" | "rejected" | "pending" | null }) {
  if (!status) return <span style={{ color: T.slate400, fontSize: 12 }}>—</span>;
  const map = {
    accepted: { label: "Accepted", color: T.emerald600, bg: T.emerald50 },
    rejected: { label: "Rejected", color: T.red600,     bg: T.red50 },
    pending:  { label: "Pending",  color: T.amber600,   bg: T.amber50 },
  };
  const cfg = map[status];
  return (
    <span style={{ padding: "2px 7px", borderRadius: 4, fontSize: 11, fontWeight: 600, backgroundColor: cfg.bg, color: cfg.color }}>
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
    <div
      style={{ position: "fixed", inset: 0, backgroundColor: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100, padding: 16 }}
      role="dialog" aria-modal="true" aria-labelledby="gen-dialog-title"
    >
      <div style={{ backgroundColor: T.white, borderRadius: 14, width: "100%", maxWidth: 480, boxShadow: "0 20px 60px rgba(0,0,0,0.18)", overflow: "hidden" }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "18px 20px", borderBottom: `1px solid ${T.slate200}` }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{ width: 36, height: 36, borderRadius: 10, backgroundColor: `${T.blue600}1A`, display: "flex", alignItems: "center", justifyContent: "center", color: T.blue600 }}>
              <Send size={18} />
            </div>
            <div>
              <h2 id="gen-dialog-title" style={{ margin: 0, fontSize: 16, fontWeight: 700, color: T.slate900 }}>Generate Submission</h2>
              <p style={{ margin: "2px 0 0", fontSize: 12, color: T.slate500 }}>Create a new CMS submission batch</p>
            </div>
          </div>
          <button onClick={onClose} disabled={generating} aria-label="Close dialog" style={{ background: "none", border: `1px solid ${T.slate200}`, borderRadius: 8, width: 32, height: 32, cursor: generating ? "not-allowed" : "pointer", display: "flex", alignItems: "center", justifyContent: "center", color: T.slate500 }}>
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Submission Type */}
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <label style={{ fontSize: 12, fontWeight: 600, color: T.slate700 }}>Submission Type</label>
            <div style={{ display: "flex", gap: 8 }}>
              {(["RAPS", "EDPS"] as SubmissionType[]).map((t) => (
                <button key={t} onClick={() => setSubmissionType(t)} disabled={generating}
                  style={{ flex: 1, padding: "10px 16px", borderRadius: 8, border: `2px solid ${submissionType === t ? T.blue600 : T.slate200}`, backgroundColor: submissionType === t ? T.blue50 : T.white, color: submissionType === t ? T.blue700 : T.slate600, fontWeight: 700, fontSize: 14, cursor: generating ? "not-allowed" : "pointer", transition: "all 0.12s" }}>
                  {t}
                </button>
              ))}
            </div>
          </div>

          {/* Payment Year */}
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <label style={{ fontSize: 12, fontWeight: 600, color: T.slate700 }}>Payment Year</label>
            <select value={paymentYear} onChange={(e) => setPaymentYear(Number(e.target.value))} disabled={generating}
              style={{ padding: "9px 12px", borderRadius: 8, border: `1px solid ${T.slate200}`, fontSize: 14, color: T.slate800, backgroundColor: T.white, cursor: generating ? "not-allowed" : "pointer" }}>
              {years.map((y) => <option key={y} value={y}>PY{y}</option>)}
            </select>
          </div>

          {/* Sweep Type */}
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <label style={{ fontSize: 12, fontWeight: 600, color: T.slate700 }}>Sweep Type</label>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              {(["Initial", "Mid-Year", "Final", "Supplemental"] as SweepType[]).map((s) => (
                <button key={s} onClick={() => setSweepType(s)} disabled={generating}
                  style={{ padding: "8px 12px", borderRadius: 8, border: `2px solid ${sweepType === s ? T.blue600 : T.slate200}`, backgroundColor: sweepType === s ? T.blue50 : T.white, color: sweepType === s ? T.blue700 : T.slate600, fontWeight: 600, fontSize: 13, cursor: generating ? "not-allowed" : "pointer", transition: "all 0.12s" }}>
                  {s}
                </button>
              ))}
            </div>
          </div>

          {/* Error */}
          {generateError && (
            <div style={{ backgroundColor: T.red50, border: `1px solid ${T.red500}40`, borderRadius: 8, padding: "12px 14px", display: "flex", alignItems: "flex-start", gap: 8 }} role="alert">
              <AlertCircle size={15} className="text-destructive" style={{ flexShrink: 0, marginTop: 1 }} />
              <span style={{ fontSize: 13, color: T.red600 }}>{generateError}</span>
            </div>
          )}

          {/* Progress */}
          {generating && (
            <div style={{ backgroundColor: T.blue50, borderRadius: 10, padding: "14px 16px", display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Loader2 size={14} style={{ color: T.blue600, animation: "spin 1s linear infinite" }} />
                <span style={{ fontSize: 13, fontWeight: 600, color: T.blue700 }}>{progressLabel}</span>
                <span style={{ marginLeft: "auto", fontSize: 12, fontWeight: 700, color: T.blue700 }}>{progress}%</span>
              </div>
              <div style={{ height: 6, borderRadius: 3, backgroundColor: T.blue100, overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${progress}%`, borderRadius: 3, backgroundColor: T.blue600, transition: "width 0.4s ease" }} />
              </div>
            </div>
          )}

          {/* Generate Button */}
          <button onClick={handleGenerate} disabled={generating} className={generating ? "" : "sub-gradient-btn"}
            style={{ width: "100%", padding: "12px 20px", borderRadius: 10, border: "none", ...(generating ? { backgroundColor: T.slate300 } : {}), color: T.white, fontWeight: 700, fontSize: 14, cursor: generating ? "not-allowed" : "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
            {generating ? (
              <><Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} />Generating…</>
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
    <div style={{ position: "fixed", inset: 0, backgroundColor: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100, padding: 16 }}
      role="dialog" aria-modal="true" aria-labelledby="upload-dialog-title">
      <div style={{ backgroundColor: T.white, borderRadius: 14, width: "100%", maxWidth: 460, boxShadow: "0 20px 60px rgba(0,0,0,0.18)", overflow: "hidden" }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "18px 20px", borderBottom: `1px solid ${T.slate200}` }}>
          <div>
            <h2 id="upload-dialog-title" style={{ margin: 0, fontSize: 16, fontWeight: 700, color: T.slate900 }}>Upload CMS Response</h2>
            <p style={{ margin: "2px 0 0", fontSize: 12, color: T.slate500 }}>{batchName}</p>
          </div>
          <button onClick={onClose} aria-label="Close dialog" style={{ background: "none", border: `1px solid ${T.slate200}`, borderRadius: 8, width: 32, height: 32, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", color: T.slate500 }}>
            <X size={16} />
          </button>
        </div>

        <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 16 }}>
          {/* File type selector */}
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <label style={{ fontSize: 12, fontWeight: 600, color: T.slate700 }}>Response File Type</label>
            <div style={{ display: "flex", gap: 8 }}>
              {(["MAO-002", "MAO-004"] as const).map((t) => (
                <button key={t} onClick={() => setFileType(t)} disabled={uploading}
                  style={{ flex: 1, padding: "9px 12px", borderRadius: 8, border: `2px solid ${fileType === t ? T.blue600 : T.slate200}`, backgroundColor: fileType === t ? T.blue50 : T.white, color: fileType === t ? T.blue700 : T.slate600, fontWeight: 700, fontSize: 13, cursor: uploading ? "not-allowed" : "pointer", transition: "all 0.12s" }}>
                  {t}
                </button>
              ))}
            </div>
            <p style={{ margin: 0, fontSize: 11, color: T.slate400 }}>
              {fileType === "MAO-002" ? "MAO-002: CMS acknowledgement of receipt (RAPS)" : "MAO-004: CMS transaction error report"}
            </p>
          </div>

          {/* Drop zone */}
          <div onDrop={handleDrop} onDragOver={(e) => { e.preventDefault(); setDragOver(true); }} onDragLeave={() => setDragOver(false)}
            onClick={() => !uploading && inputRef.current?.click()}
            style={{ border: `2px dashed ${dragOver ? T.blue500 : file ? T.emerald500 : T.slate300}`, borderRadius: 10, padding: "28px 20px", textAlign: "center", cursor: uploading ? "not-allowed" : "pointer", backgroundColor: dragOver ? T.blue50 : file ? T.emerald50 : T.slate50, transition: "all 0.12s" }}>
            <input ref={inputRef} type="file" accept=".txt,.dat" style={{ display: "none" }} onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])} />
            {file ? (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
                <FileCheck size={28} style={{ color: T.emerald600 }} />
                <span style={{ fontSize: 14, fontWeight: 600, color: T.slate800 }}>{file.name}</span>
                <span style={{ fontSize: 12, color: T.slate500 }}>{(file.size / 1024).toFixed(1)} KB</span>
                {!uploading && (
                  <button onClick={(e) => { e.stopPropagation(); setFile(null); setParsed(null); }}
                    style={{ fontSize: 11, color: T.slate500, background: "none", border: "none", cursor: "pointer", textDecoration: "underline" }}>
                    Remove
                  </button>
                )}
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
                <Upload size={28} className="text-muted-foreground" />
                <span style={{ fontSize: 14, fontWeight: 600, color: T.slate700 }}>Drop response file here</span>
                <span style={{ fontSize: 12, color: T.slate500 }}>or click to browse — .txt, .dat</span>
              </div>
            )}
          </div>

          {/* Upload error */}
          {uploadError && (
            <div style={{ backgroundColor: T.red50, border: `1px solid ${T.red500}40`, borderRadius: 8, padding: "12px 14px", display: "flex", alignItems: "flex-start", gap: 8 }} role="alert">
              <AlertCircle size={15} className="text-destructive" style={{ flexShrink: 0, marginTop: 1 }} />
              <span style={{ fontSize: 13, color: T.red600 }}>{uploadError}</span>
            </div>
          )}

          {/* Parsed results */}
          {parsed && (
            <div style={{ backgroundColor: T.emerald50, border: `1px solid ${T.emerald500}33`, borderRadius: 10, padding: "14px 16px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 10 }}>
                <CheckCircle size={15} style={{ color: T.emerald600 }} />
                <span style={{ fontSize: 13, fontWeight: 700, color: T.emerald600 }}>File parsed successfully</span>
              </div>
              <div style={{ display: "flex", gap: 20 }}>
                <div>
                  <div style={{ fontSize: 18, fontWeight: 800, color: T.slate900 }}>{parsed.total?.toLocaleString() ?? "0"}</div>
                  <div style={{ fontSize: 11, color: T.slate500 }}>Total Records</div>
                </div>
                <div>
                  <div style={{ fontSize: 18, fontWeight: 800, color: T.emerald600 }}>{parsed.accepted?.toLocaleString() ?? "0"}</div>
                  <div style={{ fontSize: 11, color: T.slate500 }}>Accepted</div>
                </div>
                <div>
                  <div style={{ fontSize: 18, fontWeight: 800, color: T.red600 }}>{parsed.rejected?.toLocaleString() ?? "0"}</div>
                  <div style={{ fontSize: 11, color: T.slate500 }}>Rejected</div>
                </div>
              </div>
            </div>
          )}

          {/* Actions */}
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={onClose}
              style={{ flex: 1, padding: "10px", borderRadius: 8, border: `1px solid ${T.slate200}`, backgroundColor: T.white, color: T.slate600, fontWeight: 600, fontSize: 13, cursor: "pointer" }}>
              {parsed ? "Close" : "Cancel"}
            </button>
            {!parsed && (
              <button onClick={handleUpload} disabled={!file || uploading} className={!file || uploading ? "" : "sub-gradient-btn"}
                style={{ flex: 2, padding: "10px", borderRadius: 8, border: "none", ...(!file || uploading ? { backgroundColor: T.slate300 } : {}), color: T.white, fontWeight: 700, fontSize: 13, cursor: !file || uploading ? "not-allowed" : "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
                {uploading ? (
                  <><Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} />Parsing…</>
                ) : (
                  <><Upload size={14} />Upload &amp; Parse</>
                )}
              </button>
            )}
            {parsed && (
              <button onClick={() => { onSuccess(); onClose(); }}
                style={{ flex: 2, padding: "10px", borderRadius: 8, border: "none", backgroundColor: T.emerald600, color: T.white, fontWeight: 700, fontSize: 13, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
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

  const colHeader: React.CSSProperties = {
    padding: "9px 12px", fontSize: 11, fontWeight: 700, color: T.slate500,
    textTransform: "uppercase", letterSpacing: "0.06em", textAlign: "left",
    borderBottom: `2px solid ${T.slate200}`,
    background: `linear-gradient(180deg, ${T.slate50} 0%, ${T.white} 100%)`,
    whiteSpace: "nowrap",
  };

  const cell: React.CSSProperties = {
    padding: "11px 12px", fontSize: 12, color: T.slate700,
    borderBottom: `1px solid ${T.slate100}`, verticalAlign: "middle",
    transition: "background-color 0.15s ease",
  };

  return (
    <div className="premium-card animate-fade-in" style={{ overflow: "hidden", marginTop: 16 }}>
      {/* Panel header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 20px", borderBottom: `1px solid ${T.slate200}`, backgroundColor: T.slate50 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <FileText size={16} style={{ color: T.blue600 }} />
          <span style={{ fontSize: 14, fontWeight: 700, color: T.slate900 }}>Batch {data?.batch.batch_id ?? batchId}</span>
          {data && <StatusBadge status={data.batch.status} />}
          {data && <TypeBadge type={data.batch.submission_type} />}
        </div>
        <button onClick={onClose} aria-label="Close detail panel"
          style={{ width: 28, height: 28, borderRadius: 6, border: `1px solid ${T.slate200}`, background: T.white, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", color: T.slate500 }}>
          <X size={14} />
        </button>
      </div>

      {/* Tab strip */}
      <div style={{ display: "flex", gap: 0, borderBottom: `1px solid ${T.slate200}`, backgroundColor: T.white, overflowX: "auto" }}>
        {tabs.map((t) => {
          const active = tab === t.key;
          return (
            <button key={t.key} onClick={() => setTab(t.key)}
              style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "11px 18px", fontSize: 13, fontWeight: active ? 700 : 500, color: active ? T.blue600 : T.slate500, background: "none", border: "none", borderBottom: active ? `2px solid ${T.blue600}` : "2px solid transparent", cursor: "pointer", whiteSpace: "nowrap", transition: "color 0.12s" }}>
              {t.icon}{t.label}
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      {isLoading ? (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 48, gap: 10, color: T.slate400 }}>
          <Loader2 size={20} style={{ animation: "spin 1s linear infinite" }} />
          <span style={{ fontSize: 14 }}>Loading batch detail…</span>
        </div>
      ) : isError ? (
        <div style={{ margin: 20, padding: "14px 16px", borderRadius: 10, border: `1px solid ${T.red500}40`, backgroundColor: T.red50, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }} role="alert">
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <AlertCircle size={16} style={{ color: T.red600, flexShrink: 0 }} />
            <span style={{ fontSize: 13, fontWeight: 600, color: T.red600 }}>
              {(error as any)?.response?.data?.detail ?? (error as any)?.message ?? "Failed to load batch detail."}
            </span>
          </div>
          <button onClick={() => refetch()}
            style={{ padding: "5px 12px", borderRadius: 6, border: `1px solid ${T.red500}40`, backgroundColor: T.white, color: T.red600, fontWeight: 600, fontSize: 12, cursor: "pointer", flexShrink: 0 }}>
            Retry
          </button>
        </div>
      ) : !data ? null : (
        <div style={{ padding: 0 }}>
          {/* ── RECORDS TAB ── */}
          {tab === "records" && (
            <>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 860 }}>
                  <thead>
                    <tr>
                      <th style={colHeader}>Patient</th>
                      <th style={colHeader}>ICD-10</th>
                      <th style={colHeader}>HCC</th>
                      <th style={colHeader}>DOS</th>
                      <th style={colHeader}>Through Date</th>
                      <th style={colHeader}>Provider NPI</th>
                      <th style={colHeader}>Validation</th>
                      <th style={colHeader}>CMS Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data.records ?? []).slice(recordPage * PAGE, (recordPage + 1) * PAGE).map((r) => (
                      <tr key={r.id} style={{ transition: "background-color 0.1s" }}>
                        <td style={cell}>
                          <div style={{ fontWeight: 600, color: T.slate800, fontSize: 12 }}>{r.patient_name}</div>
                          <div style={{ fontSize: 10, color: T.slate400, fontFamily: "monospace" }}>{r.patient_id}</div>
                        </td>
                        <td style={cell}>
                          <span style={{ fontFamily: "monospace", fontSize: 12, fontWeight: 700, color: T.blue700, backgroundColor: T.blue50, padding: "2px 6px", borderRadius: 4 }}>
                            {r.icd10_code}
                          </span>
                        </td>
                        <td style={cell}>
                          {r.hcc_code ? (
                            <div>
                              <span style={{ fontWeight: 700, color: T.violet600, fontSize: 12 }}>HCC{r.hcc_code}</span>
                              <div style={{ fontSize: 10, color: T.slate400, maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.hcc_description}</div>
                            </div>
                          ) : (
                            <span style={{ color: T.slate400, fontSize: 12 }}>—</span>
                          )}
                        </td>
                        <td style={{ ...cell, fontFamily: "monospace", color: T.slate600 }}>{r.date_of_service}</td>
                        <td style={{ ...cell, fontFamily: "monospace", color: T.slate600 }}>{r.through_date}</td>
                        <td style={{ ...cell, fontFamily: "monospace", fontSize: 11, color: T.slate500 }}>{r.provider_id}</td>
                        <td style={cell}><ValidationBadge status={r.validation_status} /></td>
                        <td style={cell}>
                          <div>
                            <CmsStatusBadge status={r.cms_status} />
                            {r.rejection_reason && (
                              <div style={{ fontSize: 10, color: T.red500, marginTop: 3, maxWidth: 140 }}>{r.rejection_reason}</div>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {/* Pagination */}
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 16px", borderTop: `1px solid ${T.slate100}` }}>
                <span style={{ fontSize: 12, color: T.slate500 }}>
                  Showing {recordPage * PAGE + 1}–{Math.min((recordPage + 1) * PAGE, (data.records ?? []).length)} of {(data.records ?? []).length}
                </span>
                <div style={{ display: "flex", gap: 6 }}>
                  <button onClick={() => setRecordPage((p) => Math.max(0, p - 1))} disabled={recordPage === 0}
                    style={{ padding: "4px 12px", borderRadius: 6, border: `1px solid ${T.slate200}`, background: T.white, color: recordPage === 0 ? T.slate300 : T.slate600, cursor: recordPage === 0 ? "not-allowed" : "pointer", fontSize: 12 }}>
                    Prev
                  </button>
                  <button onClick={() => setRecordPage((p) => p + 1)} disabled={(recordPage + 1) * PAGE >= (data.records ?? []).length}
                    style={{ padding: "4px 12px", borderRadius: 6, border: `1px solid ${T.slate200}`, background: T.white, color: (recordPage + 1) * PAGE >= (data.records ?? []).length ? T.slate300 : T.slate600, cursor: (recordPage + 1) * PAGE >= (data.records ?? []).length ? "not-allowed" : "pointer", fontSize: 12 }}>
                    Next
                  </button>
                </div>
              </div>
            </>
          )}

          {/* ── VALIDATION TAB ── */}
          {tab === "validation" && (
            <div style={{ padding: 20 }}>
              <div style={{ display: "flex", gap: 12, marginBottom: 20 }}>
                <div style={{ flex: 1, backgroundColor: T.red50, border: `1px solid ${T.red500}33`, borderRadius: 10, padding: "14px 16px", display: "flex", alignItems: "center", gap: 12 }}>
                  <XCircle size={24} style={{ color: T.red600, flexShrink: 0 }} />
                  <div>
                    <div style={{ fontSize: 22, fontWeight: 800, color: T.red600 }}>
                      {(data.validation_issues ?? []).filter((i) => i.severity === "error").reduce((s, i) => s + i.count, 0)}
                    </div>
                    <div style={{ fontSize: 12, color: T.red500, fontWeight: 600 }}>Errors</div>
                  </div>
                </div>
                <div style={{ flex: 1, backgroundColor: T.amber50, border: `1px solid ${T.amber500}33`, borderRadius: 10, padding: "14px 16px", display: "flex", alignItems: "center", gap: 12 }}>
                  <AlertTriangle size={24} style={{ color: T.amber600, flexShrink: 0 }} />
                  <div>
                    <div style={{ fontSize: 22, fontWeight: 800, color: T.amber600 }}>
                      {(data.validation_issues ?? []).filter((i) => i.severity === "warning").reduce((s, i) => s + i.count, 0)}
                    </div>
                    <div style={{ fontSize: 12, color: T.amber500, fontWeight: 600 }}>Warnings</div>
                  </div>
                </div>
              </div>
              {(data.validation_issues ?? []).length === 0 ? (
                <div style={{ padding: 40, textAlign: "center", color: T.slate400, border: `2px dashed ${T.slate200}`, borderRadius: 10 }}>
                  <CheckCircle size={28} style={{ color: T.emerald500, marginBottom: 8, opacity: 0.7 }} />
                  <p style={{ margin: 0, fontSize: 14, fontWeight: 500, color: T.emerald600 }}>No validation issues found</p>
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {(data.validation_issues ?? []).map((issue) => (
                    <div key={issue.rule_id} className="hover-lift"
                      style={{ border: `1px solid ${issue.severity === "error" ? T.red500 + "33" : T.amber500 + "33"}`, borderLeft: `4px solid ${issue.severity === "error" ? T.red500 : T.amber500}`, borderRadius: 8, padding: "14px 16px", backgroundColor: issue.severity === "error" ? T.red50 : T.amber50 }}>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          {issue.severity === "error" ? <XCircle size={14} style={{ color: T.red600 }} /> : <AlertTriangle size={14} style={{ color: T.amber600 }} />}
                          <span style={{ fontSize: 13, fontWeight: 700, color: T.slate800 }}>{issue.rule_name}</span>
                          <span style={{ fontSize: 10, color: T.slate500, fontFamily: "monospace" }}>{issue.rule_id}</span>
                        </div>
                        <span style={{ fontSize: 12, fontWeight: 700, color: issue.severity === "error" ? T.red600 : T.amber600 }}>{issue.count} affected</span>
                      </div>
                      <p style={{ margin: "0 0 6px", fontSize: 12, color: T.slate600 }}>{issue.description}</p>
                      <div style={{ display: "flex", alignItems: "flex-start", gap: 6, backgroundColor: "rgba(255,255,255,0.6)", borderRadius: 6, padding: "8px 10px" }}>
                        <CheckCircle size={12} style={{ color: T.emerald600, flexShrink: 0, marginTop: 1 }} />
                        <span style={{ fontSize: 12, color: T.slate700 }}>{issue.recommendation}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ── RESPONSES TAB ── */}
          {tab === "responses" && (
            <div style={{ padding: 20 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
                <span style={{ fontSize: 14, fontWeight: 700, color: T.slate800 }}>Uploaded Response Files</span>
                <button onClick={() => onUploadResponse(data.batch.id, data.batch.batch_id)} className="sub-gradient-btn"
                  style={{ display: "flex", alignItems: "center", gap: 6, padding: "7px 14px", borderRadius: 8, border: "none", color: T.white, fontWeight: 600, fontSize: 12, cursor: "pointer" }}>
                  <Upload size={13} />Upload Response
                </button>
              </div>
              {(data.response_files ?? []).length === 0 ? (
                <div style={{ padding: 40, textAlign: "center", color: T.slate400, border: `2px dashed ${T.slate200}`, borderRadius: 10 }}>
                  <Inbox size={32} style={{ marginBottom: 8, opacity: 0.5 }} />
                  <p style={{ margin: 0, fontSize: 14, fontWeight: 500 }}>No response files uploaded yet</p>
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {(data.response_files ?? []).map((rf) => (
                    <div key={rf.id} className="hover-lift"
                      style={{ border: `1px solid ${T.slate200}`, borderRadius: 10, padding: "14px 16px", backgroundColor: T.white, display: "flex", alignItems: "center", gap: 16 }}>
                      <div style={{ width: 40, height: 40, borderRadius: 10, backgroundColor: T.blue50, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, color: T.blue600 }}>
                        <FileText size={18} />
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontWeight: 600, fontSize: 13, color: T.slate800 }}>{rf.file_name}</div>
                        <div style={{ fontSize: 11, color: T.slate500, marginTop: 2 }}>{rf.file_type} · Uploaded {new Date(rf.uploaded_at).toLocaleDateString()}</div>
                      </div>
                      <div style={{ display: "flex", gap: 20, textAlign: "center" }}>
                        <div>
                          <div style={{ fontSize: 16, fontWeight: 800, color: T.slate900 }}>{rf.records_parsed?.toLocaleString() ?? "0"}</div>
                          <div style={{ fontSize: 10, color: T.slate400 }}>Parsed</div>
                        </div>
                        <div>
                          <div style={{ fontSize: 16, fontWeight: 800, color: T.emerald600 }}>{rf.accepted?.toLocaleString() ?? "0"}</div>
                          <div style={{ fontSize: 10, color: T.slate400 }}>Accepted</div>
                        </div>
                        <div>
                          <div style={{ fontSize: 16, fontWeight: 800, color: T.red600 }}>{rf.rejected?.toLocaleString() ?? "0"}</div>
                          <div style={{ fontSize: 10, color: T.slate400 }}>Rejected</div>
                        </div>
                      </div>
                      <span style={{ padding: "3px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600, backgroundColor: rf.status === "parsed" ? T.emerald50 : T.amber50, color: rf.status === "parsed" ? T.emerald600 : T.amber600, flexShrink: 0 }}>
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
            <div style={{ padding: 20 }}>
              <div style={{ display: "flex", gap: 12, marginBottom: 20 }}>
                <div style={{ flex: 1, backgroundColor: T.emerald50, border: `1px solid ${T.emerald500}33`, borderRadius: 10, padding: "14px 16px" }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: T.slate500, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>Total Payment Impact</div>
                  <div style={{ fontSize: 24, fontWeight: 800, color: T.emerald600 }}>${data.total_payment_impact?.toLocaleString() ?? "0"}</div>
                </div>
                <div style={{ flex: 1, backgroundColor: T.blue50, border: `1px solid ${T.blue500}33`, borderRadius: 10, padding: "14px 16px" }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: T.slate500, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>Risk Score Adjustment</div>
                  <div style={{ fontSize: 24, fontWeight: 800, color: T.blue700 }}>+{(data.risk_score_adjustment ?? 0).toFixed(3)}</div>
                </div>
              </div>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      <th style={colHeader}>HCC</th>
                      <th style={colHeader}>Description</th>
                      <th style={{ ...colHeader, textAlign: "right" }}>Patients</th>
                      <th style={{ ...colHeader, textAlign: "right" }}>Risk Score Delta</th>
                      <th style={{ ...colHeader, textAlign: "right" }}>Payment Impact</th>
                      <th style={colHeader}>CMS Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data.reconciliation ?? []).map((r) => (
                      <tr key={r.hcc_code}>
                        <td style={cell}><span style={{ fontWeight: 700, color: T.violet600, fontFamily: "monospace" }}>HCC{r.hcc_code}</span></td>
                        <td style={{ ...cell, maxWidth: 200 }}><span style={{ fontSize: 12, color: T.slate700 }}>{r.hcc_description}</span></td>
                        <td style={{ ...cell, textAlign: "right", fontWeight: 600 }}>{r.patient_count}</td>
                        <td style={{ ...cell, textAlign: "right" }}>
                          <span style={{ fontWeight: 700, color: T.blue700, fontFamily: "monospace" }}>+{(r.risk_score_delta ?? 0).toFixed(3)}</span>
                        </td>
                        <td style={{ ...cell, textAlign: "right" }}>
                          <span style={{ fontWeight: 700, color: T.emerald600, fontFamily: "monospace" }}>${r.payment_delta?.toLocaleString() ?? "0"}</span>
                        </td>
                        <td style={cell}><CmsStatusBadge status={r.cms_status} /></td>
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
