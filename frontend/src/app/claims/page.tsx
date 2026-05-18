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
import dynamic from "next/dynamic";

// Lazy-load heavy panels — excluded from the initial paint bundle.
const LazyDetailPane = dynamic(() => import("./ClaimsDetailPane"), {
  ssr: false,
  loading: () => (
    <div style={{ padding: 20, display: "flex", flexDirection: "column", gap: 8 }}>
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} style={{ height: 36, borderRadius: 8, backgroundColor: "#F1F5F9" }} />
      ))}
    </div>
  ),
});

const LazyUploadDialog = dynamic(() => import("./ClaimsUploadDialog"), {
  ssr: false,
  loading: () => null,
});
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { tokens } from "@/styles/tokens";
import { DataQualityBanner } from "@/components/DataQualityBanner";
import { PageHeader, EmptyState } from "@/components/healthcare-ui";
import { MetricCard } from "@/components/ui/metric-card";
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

// ─── Design tokens (all from tokens.ts — no hardcoded hex) ───────────────────
const C = {
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

  // Brand palette — teal values shared from ui-utils C.brand
  teal:       "#0F766E",           // ui-utils C.brand (not in tokens yet — canonical value)
  tealSoft:   "rgba(15,118,110,0.08)",
  tealBorder: "rgba(15,118,110,0.22)",
  emerald:    tokens.riskLow,
  emeraldSoft: tokens.successSoft,
  amber:      tokens.riskMedium,
  amberSoft:  tokens.warningSoft,
  red:        tokens.danger,
  redSoft:    tokens.dangerSoft,
  violet:     "rgba(124,58,237,1)", // accentPurple dark variant
  violetSoft: "rgba(139,92,246,0.08)",
  blue:       tokens.primary,
  blueSoft:   tokens.primarySoft,
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
            <span className="text-foreground" style={{ fontSize: 13, fontWeight: 500 }}>{t.text}</span>
          </div>
        );
      })}
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
      style={{ position: "fixed", inset: 0, zIndex: 110, padding: 16, background: "rgba(15,23,42,0.55)", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div className="animate-scale-in" style={{ background: C.white, borderRadius: 14, width: "100%", maxWidth: 440, padding: 26, boxShadow: "0 20px 50px rgba(0,0,0,0.2)" }} onClick={(e) => e.stopPropagation()}>
        <div style={{ width: 48, height: 48, borderRadius: 12, background: C.redSoft, color: C.red, display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 14 }}>
          <Trash2 size={22} />
        </div>
        <h3 className="text-foreground" style={{ margin: "0 0 6px", fontSize: 17, fontWeight: 700 }}>Delete batch?</h3>
        <p className="text-muted-foreground" style={{ margin: "0 0 22px", fontSize: 13, lineHeight: 1.6 }}>
          <strong className="text-foreground">&ldquo;{normBatch(batch).name}&rdquo;</strong> and all{" "}
          {fmtN(normBatch(batch).total)} associated claim records will be permanently deleted.
          This action cannot be undone.
        </p>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
          <button onClick={onCancel} disabled={pending} style={{ height: 38, padding: "0 18px", borderRadius: 8, border: `1px solid ${C.slate200}`, background: C.white, color: C.slate600, fontSize: 13, fontWeight: 500, cursor: pending ? "not-allowed" : "pointer" }}>
            Cancel
          </button>
          <button onClick={onConfirm} disabled={pending} style={{ height: 38, padding: "0 18px", borderRadius: 8, border: "none", background: C.red, color: C.white, fontSize: 13, fontWeight: 600, cursor: pending ? "not-allowed" : "pointer", opacity: pending ? 0.6 : 1, display: "inline-flex", alignItems: "center", gap: 6 }}>
            {pending ? <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} /> : <Trash2 size={13} />}
            Delete
          </button>
        </div>
      </div>
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
        background: `linear-gradient(135deg, ${C.teal} 0%, ${tokens.successDark} 100%)`,
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
      padding: "20px 16px",
    }} className="rci-page-pad-desktop">
      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        .claims-row:hover { background: ${C.tealSoft} !important; }
        .batch-row:hover { background: ${C.tealSoft} !important; }
        @media (max-width: 640px) { .rci-page-pad-desktop { padding: 20px 16px !important; } }
        button:focus-visible { outline: 2px solid ${tokens.primary}; outline-offset: 2px; border-radius: 4px; }
        @media (max-width: 768px) { .claims-kpi-row { grid-template-columns: repeat(2, 1fr) !important; } }
        @media (max-width: 480px) { .claims-kpi-row { grid-template-columns: 1fr !important; } }
      `}</style>

      {/* Data quality banner */}
      <DataQualityBanner />

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
            background: `linear-gradient(135deg, ${C.teal} 0%, ${tokens.successDark} 100%)`,
            color: C.white, fontSize: 13, fontWeight: 600, cursor: "pointer",
            boxShadow: "0 4px 14px rgba(15,118,110,0.35)",
          }}>
            <Upload size={15} /> Upload Claims
          </button>
        }
      />

      {/* KPI row — auto-fit wraps to 2-col on mobile */}
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 16,
      }}>
        <MetricCard loading={statsQ.isLoading} label="Total Batches" value={fmtN(kpi.totalBatches)}
          subtitle={statsQ.data?.last_upload ? `Last upload ${fmtDate(statsQ.data.last_upload)}` : "No uploads yet"}
          icon={<Layers size={18} />} />
        <MetricCard loading={statsQ.isLoading} label="Total Claims" value={fmtN(kpi.totalClaims)}
          subtitle="All ingested claim records" icon={<FileText size={18} />} />
        <MetricCard loading={statsQ.isLoading} label="Matched Patients" value={fmtN(kpi.totalMatched)}
          subtitle={`${kpi.matchedPct}% of claims linked`} icon={<Users size={18} />} intent="success" />
        <MetricCard loading={statsQ.isLoading} label="Top HCCs Identified" value={fmtN(kpi.uniqueHccs)}
          subtitle="Unique HCC categories" icon={<Tag size={18} />} />
        <MetricCard loading={statsQ.isLoading} label="Revenue Opportunity" value={fmt$(kpi.revenueOpportunity)}
          subtitle="Estimated (matched × HCCs)" icon={<DollarSign size={18} />} intent="success" />
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
                    <LazyDetailPane batchId={b.id} />
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
        <LazyUploadDialog
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
