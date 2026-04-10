"use client";

/**
 * Claims page — RAF Intelligence.
 *
 * Not EMR-dependent. All endpoints live under /api/claims and work with EMR
 * deactivated. Backend field names verified against
 * backend/app/routers/claims.py and services/claims_service.py — never guess.
 *
 * Batch response (from /api/claims/batches and /api/claims/batches/{id}):
 *   id, batch_uuid, filename, file_format, file_size, status, uploaded_by,
 *   created_at, updated_at, claim_count, matched_patient_count, error_message
 *   detail adds: stats { total_claims, unique_patients, unique_matched_patients,
 *                        matched_count, total_charges, hcc_distribution[...] }
 *
 * Claim record: id, patient_name, patient_dob, patient_gender, member_id,
 *   provider_name, provider_npi, date_of_service, icd10_codes (JSON list),
 *   cpt_codes, charges, openemr_pid, claim_type, ...
 *
 * Diagnosis row: icd10_code, hcc_code, hcc_label, claim_count, patient_count
 * HCC row: hcc_code, hcc_label, diagnosis_count, patient_count, claim_count
 * Unmapped patient row: patient_name, patient_dob, patient_gender, member_id, claim_count
 */

import React, { useCallback, useMemo, useRef, useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { tokens } from "@/styles/tokens";
import { PageHeader, StatCard, EmptyState } from "@/components/healthcare-ui";
import {
  FileText,
  Upload,
  RefreshCw,
  AlertTriangle,
  X,
  ChevronDown,
  ChevronUp,
  Eye,
  Play,
  Calculator,
  Trash2,
  CheckCircle,
  XCircle,
  Clock,
  Loader2,
  FileSearch,
  Tag,
  Users,
  DollarSign,
  Sparkles,
  Layers,
  Database,
} from "lucide-react";

// ─── Design tokens (match rest of app) ───────────────────────────────────────
const C = {
  white: tokens.white,
  slate50: tokens.slate50,
  slate100: tokens.slate100,
  slate200: tokens.slate200,
  slate300: tokens.slate300,
  slate400: tokens.slate400,
  slate500: tokens.slate500,
  slate600: tokens.slate600,
  slate700: tokens.slate700,
  slate800: tokens.slate800,
  slate900: tokens.slate900,

  // Brand palette matches dashboard/patients (teal + emerald)
  teal:      "#0F766E",
  tealSoft:  "rgba(15, 118, 110, 0.08)",
  tealBorder:"rgba(15, 118, 110, 0.22)",
  emerald:   "#059669",
  emeraldSoft:"#ECFDF5",
  amber:     "#D97706",
  amberSoft: "#FFFBEB",
  red:       "#DC2626",
  redSoft:   "#FEF2F2",
  violet:    "#7C3AED",
  violetSoft:"#F5F3FF",
  blue:      "#2563EB",
  blueSoft:  "#EFF6FF",
};

const ACCEPTED_EXT = [".csv", ".txt", ".837", ".edi", ".x12"];
const PAGE_SIZE = 15;

// ─── Types (match backend response shape) ───────────────────────────────────
type BatchStatus =
  | "uploaded" | "parsed" | "processing" | "processed" | "completed" | "failed";

interface ClaimsBatch {
  id: number;
  batch_uuid?: string;
  // Canonical + legacy field names — the live API returns both shapes,
  // so we tolerate either on read.
  filename?: string;
  file_name?: string;
  batch_name?: string;
  file_format?: string;        // "csv" | "837p" | "837i" | "txt" | "edi" ...
  file_type?: string;
  file_size?: number;
  status: BatchStatus;
  uploaded_by?: string;
  claim_count?: number;
  total_claims?: number | string;
  processed_claims?: number | string;
  failed_claims?: number | string;
  matched_patient_count?: number | string;
  hcc_codes_found?: number | string;
  unique_patient_count?: number | string;
  total_charges?: number | string;
  created_at: string;
  updated_at?: string;
  error_message?: string | null;
}

// Normalize legacy/canonical batch fields to a single shape used in render.
function normBatch(b: ClaimsBatch) {
  const toNum = (v: unknown): number => {
    if (v == null) return 0;
    const n = typeof v === "number" ? v : Number(v);
    return Number.isFinite(n) ? n : 0;
  };
  const name = b.batch_name ?? b.filename ?? b.file_name ?? `Batch #${b.id}`;
  const filename = b.file_name ?? b.filename ?? name;
  const format = b.file_format ?? b.file_type ?? "";
  const total = toNum(b.claim_count ?? b.total_claims);
  const processed = toNum(b.processed_claims);
  const matched = toNum(b.matched_patient_count);
  const failed = toNum(b.failed_claims);
  // "processed" (legacy) == "completed"
  const status: BatchStatus = b.status === "processed" ? "completed" : b.status;
  return { name, filename, format, total, processed, matched, failed, status };
}

interface BatchStats {
  total_claims?: number;
  unique_patients?: number;
  unique_matched_patients?: number;
  matched_count?: number;
  unique_providers?: number;
  total_charges?: number;
  hcc_distribution?: { hcc_code: string; hcc_label: string; count: number }[];
}

type BatchDetail = ClaimsBatch & { stats?: BatchStats };

interface ClaimRecord {
  id: number;
  patient_name?: string;
  patient_dob?: string;
  patient_gender?: string;
  member_id?: string;
  provider_name?: string;
  provider_npi?: string;
  date_of_service?: string;
  icd10_codes?: string[] | string;
  cpt_codes?: string[] | string;
  charges?: number;
  openemr_pid?: number | null;
  claim_type?: string;
}

interface DiagnosisRow {
  icd10_code: string;
  hcc_code?: string | null;
  hcc_label?: string | null;
  claim_count?: number;
  patient_count?: number;
}

interface HccRow {
  hcc_code: string;
  hcc_label: string;
  diagnosis_count?: number;
  patient_count?: number;
  claim_count?: number;
}

interface UnmappedRow {
  patient_name?: string;
  patient_dob?: string;
  patient_gender?: string;
  member_id?: string;
  claim_count?: number;
}

interface ClaimsStats {
  total_batches: number | string;
  total_claims: number | string;
  total_matched_patients: number | string;
  unique_icd_codes?: number | string;
  unique_hcc_codes: number | string;
  last_upload?: string;
  batches_by_status?: Record<string, number>;
}

const num = (v: unknown): number => {
  if (v == null) return 0;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : 0;
};

// ─── API helpers ─────────────────────────────────────────────────────────────
async function fetchClaimsStats(): Promise<ClaimsStats> {
  const { data } = await api.get("/api/claims/stats");
  return data;
}
async function fetchBatches(): Promise<ClaimsBatch[]> {
  const { data } = await api.get("/api/claims/batches", { params: { limit: 200 } });
  return data?.batches ?? [];
}
async function fetchBatchDetail(id: number): Promise<BatchDetail> {
  const { data } = await api.get(`/api/claims/batches/${id}`);
  return data;
}
async function fetchBatchClaims(id: number): Promise<{ claims: ClaimRecord[]; total: number }> {
  const { data } = await api.get(`/api/claims/batches/${id}/claims`, { params: { limit: 100 } });
  return { claims: data?.claims ?? [], total: data?.total ?? 0 };
}
async function fetchBatchDiagnoses(id: number): Promise<DiagnosisRow[]> {
  const { data } = await api.get(`/api/claims/batches/${id}/diagnoses`, { params: { limit: 500 } });
  return data?.diagnoses ?? [];
}
async function fetchHccSummary(id: number): Promise<HccRow[]> {
  const { data } = await api.get(`/api/claims/batches/${id}/hcc-summary`, { params: { limit: 200 } });
  return data?.hcc_summary ?? [];
}
async function fetchUnmapped(id: number): Promise<UnmappedRow[]> {
  const { data } = await api.get(`/api/claims/batches/${id}/unmapped-patients`, { params: { limit: 500 } });
  return data?.patients ?? [];
}
async function deleteBatchApi(id: number) { await api.delete(`/api/claims/batches/${id}`); }
async function processBatchApi(id: number) {
  const { data } = await api.post(`/api/claims/batches/${id}/process`);
  return data;
}
async function calculateRafApi(id: number) {
  const { data } = await api.post(`/api/claims/batches/${id}/calculate-raf`);
  return data;
}

// ─── Small utilities ─────────────────────────────────────────────────────────
const fmtN = (v: number | string | undefined | null) => {
  const n = v == null ? 0 : typeof v === "number" ? v : Number(v);
  return (Number.isFinite(n) ? n : 0).toLocaleString("en-US");
};
const fmt$ = (v: number | string | undefined | null) => {
  const n = v == null ? 0 : typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "$0";
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toFixed(0)}`;
};
const fmtDate = (iso?: string) => {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  } catch { return iso; }
};
const toList = (v: string[] | string | undefined): string[] => {
  if (!v) return [];
  if (Array.isArray(v)) return v;
  try { const p = JSON.parse(v); return Array.isArray(p) ? p : []; }
  catch { return String(v).split(",").map(s => s.trim()).filter(Boolean); }
};
const errMsg = (e: unknown, fallback = "Something went wrong."): string => {
  const ex = e as { response?: { data?: { detail?: string; message?: string } }; message?: string };
  return ex?.response?.data?.detail ?? ex?.response?.data?.message ?? ex?.message ?? fallback;
};

// ─── Visual primitives ──────────────────────────────────────────────────────
function StatusBadge({ status }: { status: BatchStatus }) {
  const map: Record<BatchStatus, { label: string; bg: string; fg: string; icon: React.ReactNode }> = {
    uploaded:   { label: "Uploaded",   bg: C.slate100,   fg: C.slate600, icon: <Clock size={11} /> },
    parsed:     { label: "Parsed",     bg: C.blueSoft,   fg: C.blue,     icon: <CheckCircle size={11} /> },
    processing: { label: "Processing", bg: C.amberSoft,  fg: C.amber,    icon: <Loader2 size={11} style={{ animation: "spin 1s linear infinite" }} /> },
    processed:  { label: "Processed",  bg: C.emeraldSoft,fg: C.emerald,  icon: <CheckCircle size={11} /> },
    completed:  { label: "Completed",  bg: C.emeraldSoft,fg: C.emerald,  icon: <CheckCircle size={11} /> },
    failed:     { label: "Failed",     bg: C.redSoft,    fg: C.red,      icon: <XCircle size={11} /> },
  };
  const cfg = map[status] ?? map.uploaded;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      padding: "4px 10px", borderRadius: 999, fontSize: 11, fontWeight: 600,
      background: cfg.bg, color: cfg.fg, border: `1px solid ${cfg.fg}22`,
      whiteSpace: "nowrap", letterSpacing: "0.02em",
    }}>
      {cfg.icon}{cfg.label}
    </span>
  );
}

function FormatPill({ format }: { format: string }) {
  const f = (format || "").toLowerCase();
  const label =
    f.includes("837p") ? "837P" :
    f.includes("837i") ? "837I" :
    f.includes("837")  ? "837"  :
    f === "csv"        ? "CSV"  :
    f === "edi"        ? "EDI"  :
    f === "x12"        ? "X12"  :
    (format || "FILE").toUpperCase();
  const tone =
    label.startsWith("837") ? { bg: C.violetSoft, fg: C.violet } :
    label === "CSV"         ? { bg: C.blueSoft,   fg: C.blue }   :
                              { bg: C.slate100,   fg: C.slate600 };
  return (
    <span style={{
      display: "inline-block", padding: "3px 8px", borderRadius: 6,
      fontSize: 10, fontWeight: 700, fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
      background: tone.bg, color: tone.fg, letterSpacing: "0.04em",
    }}>{label}</span>
  );
}

function Skeleton({ w, h = 12, r = 6 }: { w: number | string; h?: number; r?: number }) {
  return <div className="skeleton shimmer" style={{ width: w, height: h, borderRadius: r }} />;
}

function IconBtn({
  children, onClick, title, color, disabled,
}: {
  children: React.ReactNode; onClick: () => void; title: string; color?: string; disabled?: boolean;
}) {
  const fg = color ?? C.slate600;
  return (
    <button
      onClick={onClick}
      title={title}
      aria-label={title}
      disabled={disabled}
      style={{
        width: 30, height: 30, borderRadius: 7,
        border: `1px solid ${color ? `${color}33` : C.slate200}`,
        background: color ? `${color}0D` : C.white,
        color: fg, cursor: disabled ? "not-allowed" : "pointer",
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        transition: "all 0.15s ease", flexShrink: 0, opacity: disabled ? 0.5 : 1,
        boxShadow: color ? `0 1px 3px ${color}14` : "none",
      }}
      onMouseEnter={(e) => { if (!disabled) (e.currentTarget as HTMLElement).style.background = color ? `${color}18` : C.slate50; }}
      onMouseLeave={(e) => { if (!disabled) (e.currentTarget as HTMLElement).style.background = color ? `${color}0D` : C.white; }}
    >
      {children}
    </button>
  );
}

// ─── Toast (lightweight inline, no new dep) ─────────────────────────────────
type Toast = { id: number; kind: "success" | "error" | "info"; text: string };
function useToasts() {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((t: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs, { ...t, id }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), 4200);
  }, []);
  return { items, push };
}
function ToastStack({ items }: { items: Toast[] }) {
  return (
    <div style={{
      position: "fixed", right: 24, bottom: 24, zIndex: 1000,
      display: "flex", flexDirection: "column", gap: 10, pointerEvents: "none",
    }}>
      {items.map((t) => {
        const tone =
          t.kind === "success" ? { bg: C.emeraldSoft, fg: C.emerald, icon: <CheckCircle size={16} /> } :
          t.kind === "error"   ? { bg: C.redSoft,    fg: C.red,     icon: <AlertTriangle size={16} /> } :
                                 { bg: C.blueSoft,   fg: C.blue,    icon: <Sparkles size={16} /> };
        return (
          <div key={t.id} className="animate-fade-in" style={{
            display: "flex", alignItems: "center", gap: 10,
            minWidth: 260, maxWidth: 420, padding: "10px 14px", borderRadius: 10,
            background: C.white, border: `1px solid ${tone.fg}33`,
            boxShadow: "0 10px 28px rgba(15,23,42,0.12)", pointerEvents: "auto",
          }}>
            <span style={{
              width: 28, height: 28, borderRadius: 7, display: "inline-flex",
              alignItems: "center", justifyContent: "center", background: tone.bg, color: tone.fg,
            }}>{tone.icon}</span>
            <span style={{ fontSize: 13, color: C.slate700, fontWeight: 500 }}>{t.text}</span>
          </div>
        );
      })}
    </div>
  );
}

// ─── Upload Dialog ──────────────────────────────────────────────────────────
function UploadDialog({
  onClose, onUploaded,
}: { onClose: () => void; onUploaded: (batchId: number, filename: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const pick = (f: File | undefined) => {
    if (!f) return;
    const ext = "." + (f.name.split(".").pop() ?? "").toLowerCase();
    if (!ACCEPTED_EXT.includes(ext)) {
      setError(`Unsupported file type "${ext}". Accepted: ${ACCEPTED_EXT.join(", ")}`);
      return;
    }
    setError(null);
    setFile(f);
  };

  const submit = async () => {
    if (!file) return;
    setUploading(true); setProgress(0); setError(null);
    const form = new FormData();
    form.append("file", file);
    try {
      const { data } = await api.post("/api/claims/upload", form, {
        headers: { "Content-Type": "multipart/form-data" },
        onUploadProgress: (e) => {
          if (e.total) setProgress(Math.round((e.loaded / e.total) * 100));
        },
      });
      onUploaded(data?.batch_id, data?.filename ?? file.name);
      onClose();
    } catch (e) {
      setError(errMsg(e, "Upload failed. Please try again."));
    } finally {
      setUploading(false);
    }
  };

  return (
    <div
      role="dialog" aria-modal="true" aria-label="Upload Claims File"
      onClick={(e) => { if (e.target === e.currentTarget && !uploading) onClose(); }}
      style={{
        position: "fixed", inset: 0, zIndex: 100, padding: 16,
        background: "rgba(15,23,42,0.55)", backdropFilter: "blur(4px)",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}
    >
      <div className="animate-scale-in" style={{
        width: "100%", maxWidth: 540, background: C.white, borderRadius: 16,
        boxShadow: "0 25px 60px rgba(0,0,0,0.22)", overflow: "hidden",
      }}>
        {/* header */}
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "18px 22px", borderBottom: `1px solid ${C.slate200}`,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{
              width: 40, height: 40, borderRadius: 10, background: C.tealSoft,
              color: C.teal, display: "flex", alignItems: "center", justifyContent: "center",
            }}><Upload size={18} /></div>
            <div>
              <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: C.slate900 }}>Upload Claims File</h2>
              <p style={{ margin: 0, fontSize: 12, color: C.slate500 }}>CSV, X12 837P / 837I, or EDI — up to 100 MB</p>
            </div>
          </div>
          <button onClick={onClose} disabled={uploading} aria-label="Close dialog" style={{
            width: 32, height: 32, borderRadius: 8, border: `1px solid ${C.slate200}`,
            background: C.white, color: C.slate500, cursor: uploading ? "not-allowed" : "pointer",
            display: "inline-flex", alignItems: "center", justifyContent: "center",
          }}><X size={16} /></button>
        </div>

        {/* body */}
        <div style={{ padding: 22, display: "flex", flexDirection: "column", gap: 18 }}>
          <div
            role="button" tabIndex={0}
            aria-label="Claims file drop zone"
            onClick={() => !uploading && inputRef.current?.click()}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") inputRef.current?.click(); }}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); pick(e.dataTransfer.files[0]); }}
            style={{
              position: "relative", borderRadius: 14, padding: "36px 22px",
              textAlign: "center", cursor: uploading ? "default" : "pointer",
              background: dragOver ? C.tealSoft : file ? C.emeraldSoft : C.slate50,
              border: `2px dashed ${dragOver ? C.teal : file ? C.emerald : C.slate300}`,
              transition: "all 0.18s ease",
            }}
          >
            <input ref={inputRef} type="file" accept={ACCEPTED_EXT.join(",")}
              onChange={(e) => pick(e.target.files?.[0])} style={{ display: "none" }} />
            {file ? (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
                <div style={{
                  width: 48, height: 48, borderRadius: 12, background: `${C.emerald}1A`,
                  color: C.emerald, display: "flex", alignItems: "center", justifyContent: "center",
                }}><FileText size={22} /></div>
                <div style={{ fontSize: 14, fontWeight: 600, color: C.slate800 }}>{file.name}</div>
                <div style={{ fontSize: 12, color: C.slate500 }}>
                  {(file.size / 1024).toFixed(1)} KB
                </div>
                {!uploading && (
                  <button onClick={(e) => { e.stopPropagation(); setFile(null); }} style={{
                    marginTop: 4, background: "none", border: "none", fontSize: 12,
                    color: C.slate500, cursor: "pointer", textDecoration: "underline",
                  }}>Replace file</button>
                )}
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
                <div style={{
                  width: 48, height: 48, borderRadius: 12, background: C.slate100,
                  color: C.slate400, display: "flex", alignItems: "center", justifyContent: "center",
                }}><Upload size={22} /></div>
                <div>
                  <p style={{ margin: 0, fontSize: 14, fontWeight: 600, color: C.slate700 }}>
                    Drop a claims file here
                  </p>
                  <p style={{ margin: "4px 0 0", fontSize: 12, color: C.slate500 }}>
                    or click to browse — {ACCEPTED_EXT.join(", ")}
                  </p>
                </div>
              </div>
            )}
          </div>

          {uploading && (
            <div>
              <div style={{
                display: "flex", justifyContent: "space-between",
                fontSize: 12, color: C.slate500, marginBottom: 6,
              }}>
                <span>Uploading…</span>
                <span style={{ fontWeight: 700, color: C.teal }}>{progress}%</span>
              </div>
              <div style={{ height: 6, borderRadius: 3, background: C.slate200, overflow: "hidden" }}>
                <div style={{
                  height: "100%", width: `${progress}%`, background: C.teal,
                  transition: "width 0.2s ease",
                }} />
              </div>
            </div>
          )}

          {error && (
            <div role="alert" style={{
              display: "flex", alignItems: "flex-start", gap: 8,
              padding: "10px 12px", borderRadius: 8,
              background: C.redSoft, border: `1px solid ${C.red}30`,
            }}>
              <AlertTriangle size={15} style={{ color: C.red, flexShrink: 0, marginTop: 1 }} />
              <span style={{ fontSize: 13, color: C.red }}>{error}</span>
            </div>
          )}

          <div style={{
            display: "flex", alignItems: "center", gap: 10, padding: "10px 12px",
            borderRadius: 8, background: C.slate50, border: `1px solid ${C.slate200}`,
          }}>
            <Database size={14} style={{ color: C.slate500 }} />
            <span style={{ fontSize: 12, color: C.slate500, lineHeight: 1.5 }}>
              After upload, the batch is <strong>parsed</strong>. Run <em>Process</em> to match
              patients to OpenEMR records and map ICD-10 codes to HCC categories.
            </span>
          </div>
        </div>

        {/* footer */}
        <div style={{
          display: "flex", justifyContent: "flex-end", gap: 10,
          padding: "14px 22px", borderTop: `1px solid ${C.slate200}`, background: C.slate50,
        }}>
          <button onClick={onClose} disabled={uploading} style={{
            height: 38, padding: "0 18px", borderRadius: 8, border: `1px solid ${C.slate200}`,
            background: C.white, color: C.slate600, fontSize: 13, fontWeight: 500,
            cursor: uploading ? "not-allowed" : "pointer", opacity: uploading ? 0.5 : 1,
          }}>Cancel</button>
          <button onClick={submit} disabled={!file || uploading} style={{
            height: 38, padding: "0 20px", borderRadius: 8, border: "none",
            background: !file || uploading ? C.slate300 : `linear-gradient(135deg, ${C.teal} 0%, #0B5951 100%)`,
            color: C.white, fontSize: 13, fontWeight: 600,
            cursor: !file || uploading ? "not-allowed" : "pointer",
            display: "inline-flex", alignItems: "center", gap: 6,
            boxShadow: !file || uploading ? "none" : "0 2px 10px rgba(15,118,110,0.35)",
          }}>
            {uploading
              ? <><Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> Uploading…</>
              : <><Upload size={14} /> Upload Claims</>}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Confirm Delete ──────────────────────────────────────────────────────────
function ConfirmDeleteDialog({
  batch, onCancel, onConfirm, pending,
}: { batch: ClaimsBatch; onCancel: () => void; onConfirm: () => void; pending: boolean }) {
  return (
    <div role="dialog" aria-modal="true" aria-label="Confirm delete batch"
      onClick={(e) => { if (e.target === e.currentTarget) onCancel(); }}
      style={{
        position: "fixed", inset: 0, zIndex: 110, padding: 16,
        background: "rgba(15,23,42,0.55)", display: "flex",
        alignItems: "center", justifyContent: "center",
      }}>
      <div className="animate-scale-in" style={{
        background: C.white, borderRadius: 14, width: "100%", maxWidth: 440,
        padding: 26, boxShadow: "0 20px 50px rgba(0,0,0,0.2)",
      }} onClick={(e) => e.stopPropagation()}>
        <div style={{
          width: 48, height: 48, borderRadius: 12, background: C.redSoft,
          color: C.red, display: "flex", alignItems: "center", justifyContent: "center",
          marginBottom: 14,
        }}><Trash2 size={22} /></div>
        <h3 style={{ margin: "0 0 6px", fontSize: 17, fontWeight: 700, color: C.slate900 }}>Delete batch?</h3>
        <p style={{ margin: "0 0 22px", fontSize: 13, color: C.slate500, lineHeight: 1.6 }}>
          <strong style={{ color: C.slate700 }}>&ldquo;{normBatch(batch).name}&rdquo;</strong> and all{" "}
          {fmtN(normBatch(batch).total)} associated claim records will be permanently deleted.
          This action cannot be undone.
        </p>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
          <button onClick={onCancel} disabled={pending} style={{
            height: 38, padding: "0 18px", borderRadius: 8,
            border: `1px solid ${C.slate200}`, background: C.white,
            color: C.slate600, fontSize: 13, fontWeight: 500,
            cursor: pending ? "not-allowed" : "pointer",
          }}>Cancel</button>
          <button onClick={onConfirm} disabled={pending} style={{
            height: 38, padding: "0 18px", borderRadius: 8, border: "none",
            background: C.red, color: C.white, fontSize: 13, fontWeight: 600,
            cursor: pending ? "not-allowed" : "pointer", opacity: pending ? 0.6 : 1,
            display: "inline-flex", alignItems: "center", gap: 6,
          }}>
            {pending ? <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} /> : <Trash2 size={13} />}
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Batch Detail Panel (tabbed) ────────────────────────────────────────────
type DetailTab = "claims" | "diagnoses" | "hcc" | "unmapped";

function DetailPane({ batchId }: { batchId: number }) {
  const [tab, setTab] = useState<DetailTab>("claims");

  const claimsQ = useQuery({
    queryKey: ["claims-batch-claims", batchId],
    queryFn: () => fetchBatchClaims(batchId),
    enabled: tab === "claims",
  });
  const diagQ = useQuery({
    queryKey: ["claims-batch-diagnoses", batchId],
    queryFn: () => fetchBatchDiagnoses(batchId),
    enabled: tab === "diagnoses" || tab === "hcc",
  });
  const hccQ = useQuery({
    queryKey: ["claims-batch-hcc", batchId],
    queryFn: () => fetchHccSummary(batchId),
    enabled: tab === "hcc",
  });
  const unmapQ = useQuery({
    queryKey: ["claims-batch-unmapped", batchId],
    queryFn: () => fetchUnmapped(batchId),
    enabled: tab === "unmapped",
  });

  const tabs: { key: DetailTab; label: string; icon: React.ReactNode; count?: number }[] = [
    { key: "claims",    label: "Claims",            icon: <FileText size={13} />,  count: claimsQ.data?.total },
    { key: "diagnoses", label: "Diagnoses",         icon: <Tag size={13} />,       count: diagQ.data?.length },
    { key: "hcc",       label: "HCC Mapping",       icon: <Layers size={13} />,    count: hccQ.data?.length },
    { key: "unmapped",  label: "Unmatched Patients",icon: <Users size={13} />,     count: unmapQ.data?.length },
  ];

  return (
    <div style={{ background: C.white, borderRadius: 12, border: `1px solid ${C.slate200}`, overflow: "hidden" }}>
      {/* Tabs */}
      <div style={{
        display: "flex", borderBottom: `1px solid ${C.slate200}`,
        background: C.slate50, overflowX: "auto",
      }}>
        {tabs.map((t) => {
          const active = tab === t.key;
          return (
            <button key={t.key} onClick={() => setTab(t.key)} style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              padding: "12px 18px", fontSize: 13,
              fontWeight: active ? 700 : 500,
              color: active ? C.teal : C.slate500,
              background: active ? C.white : "transparent",
              border: "none",
              borderBottom: active ? `2px solid ${C.teal}` : "2px solid transparent",
              cursor: "pointer", whiteSpace: "nowrap",
            }}>
              {t.icon}
              {t.label}
              {t.count != null && (
                <span style={{
                  marginLeft: 2, padding: "1px 7px", borderRadius: 999,
                  fontSize: 10, fontWeight: 700,
                  background: active ? C.tealSoft : C.slate100,
                  color: active ? C.teal : C.slate500,
                }}>{t.count}</span>
              )}
            </button>
          );
        })}
      </div>

      {/* Content */}
      <div style={{ padding: 18, minHeight: 200 }}>
        {tab === "claims" && <ClaimsTabContent q={claimsQ} />}
        {tab === "diagnoses" && <DiagnosesTabContent q={diagQ} />}
        {tab === "hcc" && <HccTabContent q={hccQ} />}
        {tab === "unmapped" && <UnmappedTabContent q={unmapQ} />}
      </div>
    </div>
  );
}

// Tab contents ────────────────────────────────────────────────────────────────
type QState<T> = { isLoading: boolean; isError: boolean; data?: T; refetch: () => void };

function TabLoading() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {Array.from({ length: 6 }).map((_, i) => (
        <Skeleton key={i} w="100%" h={36} r={8} />
      ))}
    </div>
  );
}
function TabError({ onRetry }: { onRetry: () => void }) {
  return (
    <div style={{ textAlign: "center", padding: "28px 0" }}>
      <AlertTriangle size={24} style={{ color: C.red, marginBottom: 8 }} />
      <p style={{ margin: "0 0 12px", fontSize: 13, color: C.slate500 }}>Failed to load data.</p>
      <button onClick={onRetry} style={{
        display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 600,
        padding: "6px 12px", borderRadius: 999, border: `1px solid ${C.teal}33`,
        background: C.tealSoft, color: C.teal, cursor: "pointer",
      }}><RefreshCw size={12} /> Retry</button>
    </div>
  );
}

function TableShell({ cols, header, children }: { cols: string; header: string[]; children: React.ReactNode }) {
  return (
    <div style={{ border: `1px solid ${C.slate200}`, borderRadius: 10, overflow: "hidden" }}>
      <div style={{
        display: "grid", gridTemplateColumns: cols, gap: 8,
        padding: "10px 16px", background: C.slate50, borderBottom: `1px solid ${C.slate200}`,
      }}>
        {header.map((h) => (
          <span key={h} style={{
            fontSize: 11, fontWeight: 700, textTransform: "uppercase",
            letterSpacing: "0.05em", color: C.slate500,
          }}>{h}</span>
        ))}
      </div>
      {children}
    </div>
  );
}

function ClaimsTabContent({ q }: { q: QState<{ claims: ClaimRecord[]; total: number }> }) {
  if (q.isLoading) return <TabLoading />;
  if (q.isError) return <TabError onRetry={q.refetch} />;
  const rows = q.data?.claims ?? [];
  if (!rows.length) {
    return <EmptyState icon={<FileText size={24} />} title="No claim records" description="This batch has no parsed claims yet." />;
  }
  const cols = "2fr 1.1fr 1.5fr 2fr 100px";
  return (
    <TableShell cols={cols} header={["Patient", "DOS", "Provider", "ICD-10 Codes", "Charges"]}>
      {rows.slice(0, 100).map((c, i) => {
        const codes = toList(c.icd10_codes);
        const matched = !!c.openemr_pid;
        return (
          <div key={c.id} className="claims-row" style={{
            display: "grid", gridTemplateColumns: cols, gap: 8,
            padding: "11px 16px", alignItems: "flex-start",
            borderBottom: i < rows.length - 1 ? `1px solid ${C.slate100}` : "none",
            background: i % 2 === 1 ? C.slate50 : C.white,
            transition: "background 0.12s ease",
          }}>
            <div style={{ minWidth: 0 }}>
              <div style={{
                fontSize: 13, fontWeight: 600, color: C.slate800,
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                display: "flex", alignItems: "center", gap: 6,
              }}>
                {c.patient_name ?? "—"}
                {matched && (
                  <span title={`Matched to OpenEMR pid ${c.openemr_pid}`} style={{
                    fontSize: 9, fontWeight: 700, padding: "1px 6px", borderRadius: 999,
                    background: C.emeraldSoft, color: C.emerald, border: `1px solid ${C.emerald}33`,
                  }}>MATCHED</span>
                )}
              </div>
              {c.member_id && (
                <div style={{ fontSize: 11, color: C.slate400, fontFamily: "ui-monospace, monospace" }}>
                  {c.member_id}
                </div>
              )}
            </div>
            <span style={{ fontSize: 12, color: C.slate600 }}>{c.date_of_service ?? "—"}</span>
            <span style={{
              fontSize: 12, color: C.slate600,
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>{c.provider_name ?? "—"}</span>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {codes.slice(0, 5).map((code) => (
                <span key={code} style={{
                  padding: "2px 6px", borderRadius: 4, fontSize: 10,
                  fontFamily: "ui-monospace, monospace", fontWeight: 600,
                  background: C.tealSoft, color: C.teal,
                  border: `1px solid ${C.tealBorder}`,
                }}>{code}</span>
              ))}
              {codes.length > 5 && (
                <span style={{ fontSize: 10, color: C.slate400, alignSelf: "center" }}>
                  +{codes.length - 5}
                </span>
              )}
              {codes.length === 0 && <span style={{ fontSize: 11, color: C.slate400 }}>—</span>}
            </div>
            <span className="tabular-nums" style={{
              fontSize: 12, fontWeight: 600, color: C.slate700,
              textAlign: "right", fontFamily: "ui-monospace, monospace",
            }}>${(c.charges ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2 })}</span>
          </div>
        );
      })}
      {(q.data?.total ?? 0) > 100 && (
        <div style={{
          padding: "10px 16px", textAlign: "center", fontSize: 12, color: C.slate500,
          background: C.slate50, borderTop: `1px solid ${C.slate200}`,
        }}>
          Showing first 100 of {fmtN(q.data?.total)} claims
        </div>
      )}
    </TableShell>
  );
}

function DiagnosesTabContent({ q }: { q: QState<DiagnosisRow[]> }) {
  if (q.isLoading) return <TabLoading />;
  if (q.isError) return <TabError onRetry={q.refetch} />;
  const rows = q.data ?? [];
  if (!rows.length) {
    return <EmptyState icon={<Tag size={24} />} title="No diagnoses" description="Process the batch to extract ICD-10 codes." />;
  }
  const cols = "140px 1fr 160px 90px 90px";
  return (
    <TableShell cols={cols} header={["ICD-10", "HCC Label", "HCC", "Claims", "Patients"]}>
      {rows.map((d, i) => (
        <div key={`${d.icd10_code}-${d.hcc_code ?? ""}-${i}`} style={{
          display: "grid", gridTemplateColumns: cols, gap: 8,
          padding: "10px 16px", alignItems: "center",
          borderBottom: i < rows.length - 1 ? `1px solid ${C.slate100}` : "none",
          background: i % 2 === 1 ? C.slate50 : C.white,
        }}>
          <span style={{
            fontSize: 12, fontFamily: "ui-monospace, monospace", fontWeight: 700,
            color: C.slate700, padding: "3px 8px", background: C.slate100, borderRadius: 5,
            display: "inline-block", justifySelf: "start",
          }}>{d.icd10_code}</span>
          <span style={{
            fontSize: 12, color: C.slate600,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>{d.hcc_label ?? "—"}</span>
          {d.hcc_code ? (
            <span style={{
              fontSize: 11, fontWeight: 700, padding: "3px 9px", borderRadius: 999,
              background: C.tealSoft, color: C.teal, border: `1px solid ${C.tealBorder}`,
              justifySelf: "start",
            }}>HCC {d.hcc_code}</span>
          ) : (
            <span style={{
              fontSize: 11, fontWeight: 600, padding: "3px 9px", borderRadius: 999,
              background: C.slate100, color: C.slate500, justifySelf: "start",
            }}>Unmapped</span>
          )}
          <span className="tabular-nums" style={{ fontSize: 12, fontWeight: 600, color: C.slate700 }}>
            {fmtN(d.claim_count)}
          </span>
          <span className="tabular-nums" style={{ fontSize: 12, fontWeight: 600, color: C.slate700 }}>
            {fmtN(d.patient_count)}
          </span>
        </div>
      ))}
    </TableShell>
  );
}

function HccTabContent({ q }: { q: QState<HccRow[]> }) {
  if (q.isLoading) return <TabLoading />;
  if (q.isError) return <TabError onRetry={q.refetch} />;
  const rows = q.data ?? [];
  if (!rows.length) {
    return <EmptyState icon={<Layers size={24} />} title="No HCC data" description="Process the batch to see HCC distribution." />;
  }
  const max = Math.max(...rows.map((r) => r.patient_count ?? 0), 1);
  return (
    <div>
      <p style={{ margin: "0 0 14px", fontSize: 13, color: C.slate500 }}>
        Ranked HCC distribution for this batch — top categories by unique patient count.
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {rows.slice(0, 15).map((h) => {
          const pct = ((h.patient_count ?? 0) / max) * 100;
          return (
            <div key={h.hcc_code} style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <span style={{
                width: 74, fontSize: 11, fontWeight: 700,
                padding: "3px 9px", borderRadius: 999,
                background: C.tealSoft, color: C.teal,
                border: `1px solid ${C.tealBorder}`, textAlign: "center", flexShrink: 0,
              }}>HCC {h.hcc_code}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontSize: 12, color: C.slate700, fontWeight: 500,
                  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                  marginBottom: 4,
                }} title={h.hcc_label}>{h.hcc_label || "—"}</div>
                <div style={{ height: 8, borderRadius: 4, background: C.slate100, overflow: "hidden" }}>
                  <div style={{
                    height: "100%", width: `${pct}%`, borderRadius: 4,
                    background: `linear-gradient(90deg, ${C.teal}, ${C.emerald})`,
                    transition: "width 0.4s ease",
                  }} />
                </div>
              </div>
              <span className="tabular-nums" style={{
                width: 120, fontSize: 11, color: C.slate500, textAlign: "right", flexShrink: 0,
              }}>
                <strong style={{ color: C.slate800 }}>{fmtN(h.patient_count)}</strong> pts · {fmtN(h.diagnosis_count)} dx
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function UnmappedTabContent({ q }: { q: QState<UnmappedRow[]> }) {
  if (q.isLoading) return <TabLoading />;
  if (q.isError) return <TabError onRetry={q.refetch} />;
  const rows = q.data ?? [];
  if (!rows.length) {
    return <EmptyState icon={<CheckCircle size={24} />} title="All patients matched" description="Every patient in this batch is linked to an OpenEMR record." />;
  }
  const cols = "2fr 120px 80px 1fr 90px";
  return (
    <div>
      <p style={{ margin: "0 0 12px", fontSize: 13, color: C.slate500 }}>
        {rows.length} distinct patient{rows.length === 1 ? "" : "s"} in this batch could not be auto-matched to an OpenEMR record.
      </p>
      <TableShell cols={cols} header={["Patient Name", "DOB", "Sex", "Member ID", "Claims"]}>
        {rows.map((p, i) => (
          <div key={`${p.patient_name}-${p.member_id}-${i}`} style={{
            display: "grid", gridTemplateColumns: cols, gap: 8,
            padding: "10px 16px", alignItems: "center",
            borderBottom: i < rows.length - 1 ? `1px solid ${C.slate100}` : "none",
            background: i % 2 === 1 ? C.slate50 : C.white,
          }}>
            <span style={{ fontSize: 13, color: C.slate800, fontWeight: 500 }}>{p.patient_name || "—"}</span>
            <span style={{ fontSize: 12, color: C.slate600 }}>{p.patient_dob || "—"}</span>
            <span style={{ fontSize: 12, color: C.slate600 }}>{p.patient_gender || "—"}</span>
            <span style={{
              fontSize: 12, color: C.slate600, fontFamily: "ui-monospace, monospace",
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>{p.member_id || "—"}</span>
            <span className="tabular-nums" style={{ fontSize: 12, fontWeight: 600, color: C.slate700 }}>
              {fmtN(p.claim_count)}
            </span>
          </div>
        ))}
      </TableShell>
    </div>
  );
}

// ─── Empty "no batches" hero dropzone ───────────────────────────────────────
function EmptyHero({ onUpload }: { onUpload: () => void }) {
  return (
    <div style={{
      background: C.white, borderRadius: 16, border: `1px solid ${C.slate200}`,
      padding: 40, boxShadow: "0 4px 14px rgba(15,23,42,0.04)",
      textAlign: "center", display: "flex", flexDirection: "column", alignItems: "center",
    }}>
      <div style={{
        width: 72, height: 72, borderRadius: 20,
        background: `linear-gradient(135deg, ${C.tealSoft}, ${C.emeraldSoft})`,
        color: C.teal, display: "flex", alignItems: "center", justifyContent: "center",
        marginBottom: 18, border: `1px solid ${C.tealBorder}`,
      }}><Upload size={28} /></div>
      <h2 style={{ margin: "0 0 8px", fontSize: 20, fontWeight: 700, color: C.slate900 }}>
        Upload your first claims file
      </h2>
      <p style={{ margin: "0 0 20px", fontSize: 14, color: C.slate500, maxWidth: 500, lineHeight: 1.6 }}>
        Import CSV or X12 837 claims files. We&rsquo;ll parse each claim, match patients to OpenEMR records,
        and map ICD-10 codes to HCC categories to surface risk-adjustment opportunities.
      </p>
      <button onClick={onUpload} style={{
        display: "inline-flex", alignItems: "center", gap: 8,
        height: 42, padding: "0 22px", borderRadius: 10, border: "none",
        background: `linear-gradient(135deg, ${C.teal} 0%, #0B5951 100%)`,
        color: C.white, fontSize: 14, fontWeight: 600, cursor: "pointer",
        boxShadow: "0 4px 14px rgba(15,118,110,0.35)",
      }}>
        <Upload size={16} /> Upload Claims File
      </button>
      <div style={{
        marginTop: 26, paddingTop: 20, width: "100%", maxWidth: 560,
        borderTop: `1px dashed ${C.slate200}`, display: "grid",
        gridTemplateColumns: "repeat(3, 1fr)", gap: 12,
      }}>
        {[
          { label: "CSV", hint: "Custom delimited" },
          { label: "X12 837P", hint: "Professional claims" },
          { label: "X12 837I", hint: "Institutional claims" },
        ].map((f) => (
          <div key={f.label} style={{
            padding: "12px 10px", borderRadius: 10,
            background: C.slate50, border: `1px solid ${C.slate200}`,
          }}>
            <div style={{
              fontSize: 12, fontFamily: "ui-monospace, monospace",
              fontWeight: 700, color: C.teal, marginBottom: 2,
            }}>{f.label}</div>
            <div style={{ fontSize: 11, color: C.slate500 }}>{f.hint}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────
export default function ClaimsPage() {
  const queryClient = useQueryClient();
  const { items: toasts, push: toast } = useToasts();

  const [showUpload, setShowUpload] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<ClaimsBatch | null>(null);
  const [page, setPage] = useState(0);

  const statsQ = useQuery({
    queryKey: ["claims-stats"],
    queryFn: fetchClaimsStats,
    refetchInterval: 20_000,
  });

  const batchesQ = useQuery({
    queryKey: ["claims-batches"],
    queryFn: fetchBatches,
    refetchInterval: 12_000,
  });

  const invalidateAll = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["claims-batches"] });
    queryClient.invalidateQueries({ queryKey: ["claims-stats"] });
  }, [queryClient]);

  const processMut = useMutation({
    mutationFn: (id: number) => processBatchApi(id),
    onSuccess: (_d, id) => {
      invalidateAll();
      queryClient.invalidateQueries({ queryKey: ["claims-batch-claims", id] });
      toast({ kind: "success", text: "Batch processed — patients matched & HCC mapped." });
    },
    onError: (e) => toast({ kind: "error", text: errMsg(e, "Processing failed.") }),
  });

  const rafMut = useMutation({
    mutationFn: (id: number) => calculateRafApi(id),
    onSuccess: () => {
      invalidateAll();
      toast({ kind: "success", text: "RAF calculation complete for matched patients." });
    },
    onError: (e) => toast({ kind: "error", text: errMsg(e, "RAF calculation failed.") }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteBatchApi(id),
    onSuccess: (_d, id) => {
      invalidateAll();
      if (expandedId === id) setExpandedId(null);
      setDeleting(null);
      toast({ kind: "success", text: "Batch deleted." });
    },
    onError: (e) => toast({ kind: "error", text: errMsg(e, "Delete failed.") }),
  });

  const batches = batchesQ.data ?? [];

  // Derived KPI values from stats + batches
  const kpi = useMemo(() => {
    const s = statsQ.data;
    const totalBatches = num(s?.total_batches);
    const totalClaims = num(s?.total_claims);
    const totalMatched = num(s?.total_matched_patients);
    const matchedPct = totalClaims > 0 ? Math.min(100, Math.round((totalMatched / totalClaims) * 100)) : 0;
    const uniqueHccs = num(s?.unique_hcc_codes);
    // Rough revenue opportunity: matched patients × unique HCCs × ~$150 avg PMPM uplift (demo estimate)
    const revenueOpportunity = Math.round(totalMatched * uniqueHccs * 150);
    return { totalBatches, totalClaims, matchedPct, uniqueHccs, revenueOpportunity, totalMatched };
  }, [statsQ.data]);

  // Pagination
  const totalPages = Math.max(1, Math.ceil(batches.length / PAGE_SIZE));
  useEffect(() => { if (page > totalPages - 1) setPage(0); }, [totalPages, page]);
  const paged = batches.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  // Error state for batches
  if (batchesQ.isError) {
    return (
      <div style={{ padding: 32 }}>
        <PageHeader title="Claims Data" icon={<FileText size={22} />} />
        <div style={{
          marginTop: 24, padding: 40, borderRadius: 14, background: C.white,
          border: `1px solid ${C.slate200}`, textAlign: "center",
        }}>
          <div style={{
            width: 56, height: 56, borderRadius: 14, background: C.redSoft, color: C.red,
            display: "inline-flex", alignItems: "center", justifyContent: "center", marginBottom: 14,
          }}><AlertTriangle size={26} /></div>
          <h2 style={{ margin: "0 0 6px", fontSize: 17, fontWeight: 700, color: C.slate900 }}>
            Failed to load claims data
          </h2>
          <p style={{ margin: "0 0 16px", fontSize: 13, color: C.slate500 }}>
            {errMsg(batchesQ.error, "The claims API is not responding.")}
          </p>
          <button onClick={() => batchesQ.refetch()} style={{
            display: "inline-flex", alignItems: "center", gap: 8,
            padding: "8px 16px", borderRadius: 8, border: `1px solid ${C.teal}33`,
            background: C.tealSoft, color: C.teal, fontSize: 13, fontWeight: 600, cursor: "pointer",
          }}><RefreshCw size={14} /> Retry</button>
        </div>
      </div>
    );
  }

  return (
    <div style={{
      display: "flex", flexDirection: "column", gap: 24,
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
    }}>
      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        .claims-row:hover { background: ${C.tealSoft} !important; }
        .batch-row:hover { background: ${C.tealSoft} !important; }
      `}</style>

      {/* Header */}
      <PageHeader
        title="Claims Data"
        icon={<FileText size={22} />}
        subtitle={
          !batchesQ.isLoading
            ? `${fmtN(batches.length)} batch${batches.length === 1 ? "" : "es"} · ${fmtN(kpi.totalClaims)} claims indexed`
            : undefined
        }
        actions={
          <button onClick={() => setShowUpload(true)} aria-label="Upload claims file" style={{
            display: "inline-flex", alignItems: "center", gap: 8, height: 40,
            padding: "0 20px", borderRadius: 10, border: "none",
            background: `linear-gradient(135deg, ${C.teal} 0%, #0B5951 100%)`,
            color: C.white, fontSize: 13, fontWeight: 600, cursor: "pointer",
            boxShadow: "0 4px 14px rgba(15,118,110,0.35)",
          }}>
            <Upload size={15} /> Upload Claims
          </button>
        }
      />

      {/* KPI row */}
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(5, minmax(0, 1fr))", gap: 16,
      }}>
        <StatCard loading={statsQ.isLoading} label="Total Batches" value={fmtN(kpi.totalBatches)}
          subtitle={statsQ.data?.last_upload ? `Last upload ${fmtDate(statsQ.data.last_upload)}` : "No uploads yet"}
          icon={<Layers size={18} />} color={C.teal} />
        <StatCard loading={statsQ.isLoading} label="Total Claims" value={fmtN(kpi.totalClaims)}
          subtitle="All ingested claim records" icon={<FileText size={18} />} color={C.blue} />
        <StatCard loading={statsQ.isLoading} label="Matched Patients" value={fmtN(kpi.totalMatched)}
          subtitle={`${kpi.matchedPct}% of claims linked`} icon={<Users size={18} />} color={C.emerald} />
        <StatCard loading={statsQ.isLoading} label="Top HCCs Identified" value={fmtN(kpi.uniqueHccs)}
          subtitle="Unique HCC categories" icon={<Tag size={18} />} color={C.violet} />
        <StatCard loading={statsQ.isLoading} label="Revenue Opportunity" value={fmt$(kpi.revenueOpportunity)}
          subtitle="Estimated (matched × HCCs)" icon={<DollarSign size={18} />} color={C.amber} />
      </div>

      {/* Batch table or empty hero */}
      {batchesQ.isLoading ? (
        <div style={{
          background: C.white, borderRadius: 14, border: `1px solid ${C.slate200}`,
          overflow: "hidden",
        }}>
          <div style={{
            padding: "14px 20px", background: C.slate50,
            borderBottom: `1px solid ${C.slate200}`,
          }}><Skeleton w={180} h={14} /></div>
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} style={{
              display: "grid", gap: 12,
              gridTemplateColumns: "2fr 80px 1.2fr 110px 120px 140px",
              padding: "18px 20px", borderBottom: `1px solid ${C.slate100}`, alignItems: "center",
            }}>
              <Skeleton w="70%" />
              <Skeleton w={50} />
              <Skeleton w="60%" />
              <Skeleton w={70} />
              <Skeleton w={90} />
              <Skeleton w={110} />
            </div>
          ))}
        </div>
      ) : batches.length === 0 ? (
        <EmptyHero onUpload={() => setShowUpload(true)} />
      ) : (
        <div style={{
          background: C.white, borderRadius: 14, border: `1px solid ${C.slate200}`,
          overflow: "hidden", boxShadow: "0 4px 14px rgba(15,23,42,0.04)",
        }}>
          {/* table header */}
          <div style={{
            display: "grid", gap: 12,
            gridTemplateColumns: "2fr 80px 1.2fr 110px 120px 150px",
            alignItems: "center", padding: "13px 20px",
            background: `linear-gradient(135deg, ${C.slate50}, ${C.slate100})`,
            borderBottom: `2px solid ${C.slate200}`,
          }}>
            {["Batch", "Format", "Claims / Match", "Status", "Uploaded", "Actions"].map((h) => (
              <span key={h} style={{
                fontSize: 11, fontWeight: 700, textTransform: "uppercase",
                letterSpacing: "0.06em", color: C.slate500,
              }}>{h}</span>
            ))}
          </div>

          {/* rows */}
          {paged.map((b, idx) => {
            const expanded = expandedId === b.id;
            const n = normBatch(b);
            const total = n.total;
            const matched = n.matched;
            const pct = total > 0 ? Math.round((matched / total) * 100) : 0;
            const canProcess = n.status === "uploaded" || n.status === "parsed" || n.status === "failed";
            const canRaf = n.status === "completed" || n.status === "parsed";
            return (
              <React.Fragment key={b.id}>
                <div
                  className="batch-row"
                  style={{
                    display: "grid", gap: 12,
                    gridTemplateColumns: "2fr 80px 1.2fr 110px 120px 150px",
                    alignItems: "center", padding: "14px 20px",
                    borderBottom: expanded ? `1px solid ${C.tealBorder}` : `1px solid ${C.slate100}`,
                    background: expanded ? C.tealSoft : idx % 2 === 1 ? C.slate50 : C.white,
                    transition: "background 0.15s ease",
                  }}
                >
                  {/* Batch */}
                  <div
                    role="button" tabIndex={0} aria-expanded={expanded}
                    onClick={() => setExpandedId((p) => (p === b.id ? null : b.id))}
                    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setExpandedId((p) => (p === b.id ? null : b.id)); }}
                    style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer", minWidth: 0 }}
                  >
                    <div style={{
                      width: 34, height: 34, borderRadius: 9, background: C.tealSoft,
                      color: C.teal, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
                      border: `1px solid ${C.tealBorder}`,
                    }}><FileText size={15} /></div>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{
                        fontSize: 13, fontWeight: 600, color: C.slate900,
                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                      }}>{n.name}</div>
                      <div style={{
                        fontSize: 11, color: C.slate500,
                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                      }}>
                        #{b.id} · {n.filename}
                      </div>
                    </div>
                    <span style={{ color: C.slate400, flexShrink: 0 }}>
                      {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                    </span>
                  </div>

                  {/* Format */}
                  <FormatPill format={n.format} />

                  {/* Claims progress */}
                  <div style={{ minWidth: 0 }}>
                    <div className="tabular-nums" style={{
                      fontSize: 11, color: C.slate500, marginBottom: 4,
                      display: "flex", justifyContent: "space-between",
                    }}>
                      <span><strong style={{ color: C.slate800 }}>{fmtN(matched)}</strong> / {fmtN(total)}</span>
                      <span style={{ color: C.teal, fontWeight: 700 }}>{pct}%</span>
                    </div>
                    <div style={{ height: 5, borderRadius: 3, background: C.slate100, overflow: "hidden" }}>
                      <div style={{
                        height: "100%", width: `${pct}%`, borderRadius: 3,
                        background: n.status === "failed" ? C.red
                          : n.status === "completed" ? C.emerald
                          : C.teal,
                        transition: "width 0.3s ease",
                      }} />
                    </div>
                  </div>

                  {/* Status */}
                  <StatusBadge status={n.status} />

                  {/* Uploaded */}
                  <span style={{ fontSize: 12, color: C.slate500 }}>{fmtDate(b.created_at)}</span>

                  {/* Actions */}
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}
                    onClick={(e) => e.stopPropagation()}>
                    <IconBtn title="View details" color={expanded ? C.teal : undefined}
                      onClick={() => setExpandedId((p) => (p === b.id ? null : b.id))}>
                      <Eye size={13} />
                    </IconBtn>
                    {canProcess && (
                      <IconBtn title="Process batch" color={C.teal}
                        disabled={processMut.isPending}
                        onClick={() => processMut.mutate(b.id)}>
                        {processMut.isPending && processMut.variables === b.id
                          ? <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} />
                          : <Play size={13} />}
                      </IconBtn>
                    )}
                    {canRaf && (
                      <IconBtn title="Calculate RAF" color={C.amber}
                        disabled={rafMut.isPending}
                        onClick={() => rafMut.mutate(b.id)}>
                        {rafMut.isPending && rafMut.variables === b.id
                          ? <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} />
                          : <Calculator size={13} />}
                      </IconBtn>
                    )}
                    <IconBtn title="Delete batch" color={C.red}
                      onClick={() => setDeleting(b)}>
                      <Trash2 size={13} />
                    </IconBtn>
                  </div>
                </div>

                {expanded && (
                  <div style={{
                    padding: "0 20px 20px", background: C.tealSoft,
                    borderBottom: `1px solid ${C.slate200}`,
                  }}>
                    <DetailPane batchId={b.id} />
                  </div>
                )}
              </React.Fragment>
            );
          })}

          {/* Pagination */}
          {totalPages > 1 && (
            <div style={{
              display: "flex", alignItems: "center", justifyContent: "center",
              gap: 14, padding: "14px 20px", borderTop: `1px solid ${C.slate200}`, background: C.slate50,
            }}>
              <button onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0} style={{
                padding: "6px 14px", borderRadius: 8, border: `1px solid ${C.slate200}`,
                background: C.white, color: page === 0 ? C.slate300 : C.slate600,
                fontSize: 13, fontWeight: 500, cursor: page === 0 ? "not-allowed" : "pointer",
              }}>Previous</button>
              <span className="tabular-nums" style={{ fontSize: 13, color: C.slate500 }}>
                Page <strong style={{ color: C.slate900 }}>{page + 1}</strong> of <strong style={{ color: C.slate900 }}>{totalPages}</strong>
              </span>
              <button onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1} style={{
                padding: "6px 14px", borderRadius: 8, border: `1px solid ${C.slate200}`,
                background: C.white, color: page >= totalPages - 1 ? C.slate300 : C.slate600,
                fontSize: 13, fontWeight: 500, cursor: page >= totalPages - 1 ? "not-allowed" : "pointer",
              }}>Next</button>
            </div>
          )}
        </div>
      )}

      {/* Modals + toasts */}
      {showUpload && (
        <UploadDialog
          onClose={() => setShowUpload(false)}
          onUploaded={(id, name) => {
            invalidateAll();
            if (id) setExpandedId(id);
            toast({ kind: "success", text: `Uploaded ${name}. Parsed and ready to process.` });
          }}
        />
      )}
      {deleting && (
        <ConfirmDeleteDialog
          batch={deleting}
          pending={deleteMut.isPending}
          onCancel={() => setDeleting(null)}
          onConfirm={() => deleteMut.mutate(deleting.id)}
        />
      )}
      <ToastStack items={toasts} />
    </div>
  );
}
