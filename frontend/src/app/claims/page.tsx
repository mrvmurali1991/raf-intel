"use client";

import React, {
  useState,
  useCallback,
  useRef,
} from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import {
  FileText,
  Upload,
  RefreshCw,
  AlertTriangle,
  X,
  ChevronLeft,
  ChevronRight,
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
  Link2,
  BarChart2,
  User,
} from "lucide-react";
import { PageHeader, StatCard, EmptyState } from "@/components/healthcare-ui";

// ─────────────────────────────────────────────
// Design Tokens (matches existing pages)
// ─────────────────────────────────────────────

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
  slate900: "#0F172A",
  blue50: "#EFF6FF",
  blue100: "#DBEAFE",
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
  gray100: "#F3F4F6",
  gray200: "#E5E7EB",
  gray400: "#9CA3AF",
  gray500: "#6B7280",
  violet500: "#8B5CF6",
};

// ─────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────

type BatchStatus =
  | "uploaded"
  | "parsing"
  | "processing"
  | "completed"
  | "failed";

interface ClaimsBatch {
  id: number;
  batch_name: string;
  file_type: string;
  file_name: string;
  total_claims: number;
  processed_claims: number;
  failed_claims: number;
  status: BatchStatus;
  created_at: string;
  updated_at: string;
}

interface ClaimRecord {
  id: number;
  patient_name: string | null;
  patient_id: string | null;
  date_of_service: string;
  provider_name: string | null;
  diagnoses: string[];
  charges: number;
  hcc_mapped: boolean;
}

interface DiagnosisRecord {
  icd10_code: string;
  description: string | null;
  hcc_code: number | null;
  hcc_label: string | null;
  count: number;
}

interface HccSummaryItem {
  hcc_code: number;
  hcc_label: string;
  patient_count: number;
}

interface UnmappedPatient {
  claim_patient_id: string;
  patient_name: string | null;
  claim_count: number;
}

interface BatchDetail {
  batch: ClaimsBatch;
  claims: ClaimRecord[];
  diagnoses: DiagnosisRecord[];
  hcc_summary: HccSummaryItem[];
  unmapped_patients: UnmappedPatient[];
}

interface ClaimsStats {
  total_batches: number;
  total_claims: number;
  total_matched_patients: number;
  unique_hcc_codes: number;
}

// ─────────────────────────────────────────────
// API helpers
// ─────────────────────────────────────────────

async function fetchClaimsStats(): Promise<ClaimsStats> {
  const { data } = await api.get(`/api/claims/stats`);
  return data;
}

async function fetchBatches(): Promise<ClaimsBatch[]> {
  const { data } = await api.get(`/api/claims/batches`);
  return Array.isArray(data) ? data : (data?.batches ?? []);
}

async function fetchBatchDetail(batchId: number): Promise<BatchDetail> {
  const { data } = await api.get(
    `/api/claims/batches/${batchId}`
  );
  return data;
}

async function deleteBatch(batchId: number): Promise<void> {
  await api.delete(`/api/claims/batches/${batchId}`);
}

async function processBatch(batchId: number): Promise<void> {
  await api.post(`/api/claims/batches/${batchId}/process`);
}

async function calculateRAF(batchId: number): Promise<void> {
  await api.post(`/api/claims/batches/${batchId}/calculate-raf`);
}

async function mapToOpenEMR(
  batchId: number,
  patientId: string
): Promise<void> {
  await api.post(
    `/api/claims/batches/${batchId}/map-patient`,
    { claim_patient_id: patientId }
  );
}

// ─────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────

const ACCEPTED_EXTENSIONS = [".csv", ".txt", ".837", ".edi"];
const ACCEPTED_MIME =
  "text/csv,text/plain,application/edi-x12,application/x-837,.csv,.txt,.837,.edi";
const PAGE_SIZE = 15;

// ─────────────────────────────────────────────
// Status Badge
// ─────────────────────────────────────────────

function StatusBadge({ status }: { status: BatchStatus }) {
  const map: Record<
    BatchStatus,
    { label: string; bg: string; color: string; icon: React.ReactNode }
  > = {
    uploaded: {
      label: "Uploaded",
      bg: T.slate100,
      color: T.slate600,
      icon: <Clock size={11} />,
    },
    parsing: {
      label: "Parsing",
      bg: T.blue100,
      color: T.blue700,
      icon: <Loader2 size={11} style={{ animation: "spin 1s linear infinite" }} />,
    },
    processing: {
      label: "Processing",
      bg: T.amber50,
      color: T.amber600,
      icon: <Loader2 size={11} style={{ animation: "spin 1s linear infinite" }} />,
    },
    completed: {
      label: "Completed",
      bg: T.emerald50,
      color: T.emerald600,
      icon: <CheckCircle size={11} />,
    },
    failed: {
      label: "Failed",
      bg: T.red50,
      color: T.red600,
      icon: <XCircle size={11} />,
    },
  };

  const cfg = map[status] ?? map.uploaded;

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        padding: "4px 12px",
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 600,
        backgroundColor: cfg.bg,
        color: cfg.color,
        whiteSpace: "nowrap",
        border: `1px solid ${cfg.color}20`,
        boxShadow: `0 1px 3px ${cfg.color}15`,
        letterSpacing: "0.02em",
      }}
    >
      {cfg.icon}
      {cfg.label}
    </span>
  );
}

// ─────────────────────────────────────────────
// File type display helper
// ─────────────────────────────────────────────

function fileTypeLabel(ext: string): string {
  const map: Record<string, string> = {
    csv: "CSV",
    txt: "TXT / Flat",
    "837": "X12 837",
    edi: "EDI",
  };
  return map[ext.toLowerCase().replace(".", "")] ?? ext.toUpperCase();
}

function detectFileType(name: string): string {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  return fileTypeLabel(ext);
}

// ─────────────────────────────────────────────
// Upload Dialog
// ─────────────────────────────────────────────

interface UploadDialogProps {
  onClose: () => void;
  onSuccess: () => void;
}

function UploadDialog({ onClose, onSuccess }: UploadDialogProps) {
  const [file, setFile] = useState<File | null>(null);
  const [batchName, setBatchName] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback((f: File) => {
    const ext = f.name.split(".").pop()?.toLowerCase() ?? "";
    if (!ACCEPTED_EXTENSIONS.includes(`.${ext}`)) {
      setError(`Unsupported file type ".${ext}". Accepted: ${ACCEPTED_EXTENSIONS.join(", ")}`);
      return;
    }
    setError(null);
    setFile(f);
    setBatchName(f.name.replace(/\.[^.]+$/, ""));
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const f = e.dataTransfer.files[0];
      if (f) handleFile(f);
    },
    [handleFile]
  );

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) handleFile(f);
  };

  const handleUpload = async () => {
    if (!file) return;
    setUploading(true);
    setError(null);
    setProgress(0);

    const form = new FormData();
    form.append("file", file);
    form.append("batch_name", batchName || file.name);

    try {
      await api.post(`/api/claims/upload`, form, {
        headers: { "Content-Type": "multipart/form-data" },
        onUploadProgress: (evt) => {
          if (evt.total) {
            setProgress(Math.round((evt.loaded / evt.total) * 100));
          }
        },
      });
      onSuccess();
      onClose();
    } catch (err: unknown) {
      setError(
        (err as { response?: { data?: { detail?: string; message?: string } } })?.response?.data?.detail ??
          (err as { response?: { data?: { message?: string } } })?.response?.data?.message ??
          "Upload failed. Please try again."
      );
    } finally {
      setUploading(false);
    }
  };

  const detectedType = file ? detectFileType(file.name) : null;

  return (
    /* Backdrop */
    <div
      style={{
        position: "fixed",
        inset: 0,
        backgroundColor: "rgba(15, 23, 42, 0.55)",
        backdropFilter: "blur(4px)",
        zIndex: 100,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-label="Upload Claims File"
    >
      <div
        className="animate-scale-in"
        style={{
          backgroundColor: T.white,
          borderRadius: 16,
          width: "100%",
          maxWidth: 520,
          boxShadow: "0 25px 60px rgba(0,0,0,0.20), 0 8px 20px rgba(0,0,0,0.10)",
          overflow: "hidden",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Dialog header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "20px 24px 16px",
            borderBottom: `1px solid ${T.slate200}`,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div
              style={{
                width: 36,
                height: 36,
                borderRadius: 10,
                backgroundColor: `${T.blue600}1A`,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: T.blue600,
              }}
            >
              <Upload size={18} />
            </div>
            <div>
              <h2
                style={{ margin: 0, fontSize: 16, fontWeight: 700, color: T.slate900 }}
              >
                Upload Claims File
              </h2>
              <p style={{ margin: 0, fontSize: 12, color: T.slate500 }}>
                Accepts CSV, TXT, X12 837, EDI
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={uploading}
            aria-label="Close dialog"
            style={{
              width: 32,
              height: 32,
              border: `1px solid ${T.slate200}`,
              borderRadius: 8,
              background: T.white,
              cursor: uploading ? "not-allowed" : "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: T.slate500,
              opacity: uploading ? 0.4 : 1,
            }}
          >
            <X size={16} />
          </button>
        </div>

        {/* Dialog body */}
        <div style={{ padding: 24, display: "flex", flexDirection: "column", gap: 20 }}>
          {/* Drop zone */}
          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => !uploading && fileInputRef.current?.click()}
            role="button"
            tabIndex={0}
            aria-label="Drop zone for claims file"
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") fileInputRef.current?.click();
            }}
            style={{
              position: "relative",
              borderRadius: 12,
              padding: "36px 24px",
              textAlign: "center",
              backgroundColor: dragOver
                ? T.blue50
                : file
                ? T.emerald50
                : T.slate50,
              cursor: uploading ? "default" : "pointer",
              transition: "all 0.2s ease",
              overflow: "hidden",
            }}
          >
            {/* Animated border using SVG */}
            <svg
              style={{
                position: "absolute",
                inset: 0,
                width: "100%",
                height: "100%",
                pointerEvents: "none",
              }}
            >
              <rect
                x="1"
                y="1"
                width="calc(100% - 2px)"
                height="calc(100% - 2px)"
                rx="11"
                ry="11"
                fill="none"
                stroke={dragOver ? T.blue500 : file ? T.emerald500 : T.slate300}
                strokeWidth="2"
                strokeDasharray="8 6"
                style={{
                  animation: dragOver ? "dash-march 0.4s linear infinite" : "dash-march 2s linear infinite",
                }}
              />
            </svg>
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPTED_MIME}
              onChange={handleInputChange}
              style={{ display: "none" }}
              aria-hidden="true"
            />

            {file ? (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
                <div
                  style={{
                    width: 44,
                    height: 44,
                    borderRadius: 12,
                    backgroundColor: `${T.emerald500}1A`,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: T.emerald600,
                  }}
                >
                  <FileText size={22} />
                </div>
                <div>
                  <p style={{ margin: 0, fontSize: 14, fontWeight: 600, color: T.slate800 }}>
                    {file.name}
                  </p>
                  <p style={{ margin: "2px 0 0", fontSize: 12, color: T.slate500 }}>
                    {(file.size / 1024).toFixed(1)} KB
                    {detectedType && (
                      <span
                        style={{
                          marginLeft: 8,
                          padding: "2px 7px",
                          borderRadius: 4,
                          fontSize: 11,
                          fontWeight: 600,
                          backgroundColor: `${T.blue600}1A`,
                          color: T.blue700,
                        }}
                      >
                        {detectedType}
                      </span>
                    )}
                  </p>
                </div>
                {!uploading && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setFile(null);
                      setBatchName("");
                    }}
                    style={{
                      marginTop: 4,
                      fontSize: 12,
                      color: T.slate500,
                      background: "none",
                      border: "none",
                      cursor: "pointer",
                      textDecoration: "underline",
                    }}
                  >
                    Remove
                  </button>
                )}
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
                <div
                  style={{
                    width: 44,
                    height: 44,
                    borderRadius: 12,
                    backgroundColor: T.slate100,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: T.slate400,
                  }}
                >
                  <Upload size={22} />
                </div>
                <div>
                  <p style={{ margin: 0, fontSize: 14, fontWeight: 600, color: T.slate700 }}>
                    Drop your claims file here
                  </p>
                  <p style={{ margin: "4px 0 0", fontSize: 12, color: T.slate500 }}>
                    or click to browse &mdash; .csv, .txt, .837, .edi
                  </p>
                </div>
              </div>
            )}
          </div>

          {/* Batch name */}
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <label
              htmlFor="batch-name-input"
              style={{ fontSize: 13, fontWeight: 600, color: T.slate700 }}
            >
              Batch Name
            </label>
            <input
              id="batch-name-input"
              type="text"
              value={batchName}
              onChange={(e) => setBatchName(e.target.value)}
              placeholder={`e.g. Q1_${new Date().getFullYear()}_Claims`}
              disabled={uploading}
              style={{
                height: 38,
                borderRadius: 8,
                border: `1px solid ${T.slate200}`,
                paddingLeft: 12,
                paddingRight: 12,
                fontSize: 13,
                color: T.slate800,
                backgroundColor: T.white,
                outline: "none",
                opacity: uploading ? 0.6 : 1,
              }}
            />
          </div>

          {/* Progress bar */}
          {uploading && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: 12,
                  color: T.slate500,
                }}
              >
                <span>Uploading&hellip;</span>
                <span style={{ fontWeight: 600, color: T.blue600 }}>{progress}%</span>
              </div>
              <div
                style={{
                  height: 6,
                  borderRadius: 3,
                  backgroundColor: T.slate200,
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    height: "100%",
                    width: `${progress}%`,
                    borderRadius: 3,
                    backgroundColor: T.blue600,
                    transition: "width 0.2s ease",
                  }}
                />
              </div>
            </div>
          )}

          {/* Error */}
          {error && (
            <div
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: 8,
                padding: "10px 12px",
                borderRadius: 8,
                backgroundColor: T.red50,
                border: `1px solid ${T.red500}30`,
              }}
              role="alert"
            >
              <AlertTriangle size={15} style={{ color: T.red600, flexShrink: 0, marginTop: 1 }} />
              <span style={{ fontSize: 13, color: T.red600 }}>{error}</span>
            </div>
          )}
        </div>

        {/* Dialog footer */}
        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: 10,
            padding: "16px 24px",
            borderTop: `1px solid ${T.slate200}`,
            backgroundColor: T.slate50,
          }}
        >
          <button
            onClick={onClose}
            disabled={uploading}
            style={{
              height: 38,
              padding: "0 18px",
              borderRadius: 8,
              border: `1px solid ${T.slate200}`,
              backgroundColor: T.white,
              fontSize: 13,
              fontWeight: 500,
              color: T.slate600,
              cursor: uploading ? "not-allowed" : "pointer",
              opacity: uploading ? 0.5 : 1,
            }}
          >
            Cancel
          </button>
          <button
            className="btn-press"
            onClick={handleUpload}
            disabled={!file || uploading}
            style={{
              height: 38,
              padding: "0 20px",
              borderRadius: 8,
              border: "none",
              background: !file || uploading ? T.slate300 : "linear-gradient(135deg, #2563EB 0%, #1D4ED8 100%)",
              fontSize: 13,
              fontWeight: 600,
              color: T.white,
              cursor: !file || uploading ? "not-allowed" : "pointer",
              display: "flex",
              alignItems: "center",
              gap: 6,
              transition: "all 0.15s ease",
              boxShadow: !file || uploading ? "none" : "0 2px 8px rgba(37,99,235,0.3)",
            }}
          >
            {uploading ? (
              <>
                <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} />
                Uploading&hellip;
              </>
            ) : (
              <>
                <Upload size={14} />
                Upload Claims
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
// HCC Bar Chart (inline SVG-based)
// ─────────────────────────────────────────────

function HccBarChart({ items }: { items: HccSummaryItem[] }) {
  if (!items?.length) {
    return (
      <EmptyState
        icon={<BarChart2 size={24} />}
        title="No HCC data"
        description="Process the batch to see HCC distribution."
      />
    );
  }

  const maxCount = Math.max(...items.map((i) => i.patient_count), 1);
  const barColors = [
    T.blue600,
    T.emerald500,
    T.amber500,
    T.violet500,
    T.red500,
  ];

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 10,
        padding: "4px 0",
      }}
    >
      {items.slice(0, 10).map((item, idx) => {
        const pct = (item.patient_count / maxCount) * 100;
        const color = barColors[idx % barColors.length];
        return (
          <div
            key={item.hcc_code}
            style={{ display: "flex", alignItems: "center", gap: 10 }}
          >
            <span
              style={{
                fontSize: 11,
                fontWeight: 700,
                color: T.slate600,
                width: 52,
                textAlign: "right",
                flexShrink: 0,
              }}
            >
              HCC {item.hcc_code}
            </span>
            <div
              style={{
                flex: 1,
                height: 20,
                borderRadius: 4,
                backgroundColor: T.slate100,
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  height: "100%",
                  width: `${pct}%`,
                  borderRadius: 4,
                  backgroundColor: color,
                  transition: "width 0.4s ease",
                  display: "flex",
                  alignItems: "center",
                  paddingLeft: 6,
                }}
              >
                {pct > 20 && (
                  <span style={{ fontSize: 10, fontWeight: 600, color: T.white }}>
                    {item.patient_count}
                  </span>
                )}
              </div>
            </div>
            {pct <= 20 && (
              <span style={{ fontSize: 11, fontWeight: 600, color: T.slate600, width: 20 }}>
                {item.patient_count}
              </span>
            )}
            <span
              style={{
                fontSize: 11,
                color: T.slate500,
                maxWidth: 160,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
              title={item.hcc_label}
            >
              {item.hcc_label}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ─────────────────────────────────────────────
// Batch Detail Panel
// ─────────────────────────────────────────────

type DetailTab = "claims" | "diagnoses" | "hcc" | "unmapped";

interface BatchDetailPanelProps {
  batchId: number;
  onClose: () => void;
  onMapSuccess: () => void;
}

function BatchDetailPanel({
  batchId,
  onClose,
  onMapSuccess,
}: BatchDetailPanelProps) {
  const [tab, setTab] = useState<DetailTab>("claims");
  const queryClient = useQueryClient();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["batch-detail", batchId],
    queryFn: () => fetchBatchDetail(batchId),
  });

  const mapMut = useMutation({
    mutationFn: (patientId: string) => mapToOpenEMR(batchId, patientId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["batch-detail", batchId] });
      onMapSuccess();
    },
  });

  const tabs: { key: DetailTab; label: string; icon: React.ReactNode }[] = [
    { key: "claims", label: "Claims", icon: <FileText size={13} /> },
    { key: "diagnoses", label: "Diagnoses", icon: <Tag size={13} /> },
    { key: "hcc", label: "HCC Summary", icon: <BarChart2 size={13} /> },
    { key: "unmapped", label: "Unmapped Patients", icon: <User size={13} /> },
  ];

  return (
    <div
      className="premium-card animate-scale-in"
      style={{
        overflow: "hidden",
        marginTop: 0,
      }}
    >
      {/* Panel header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "14px 20px",
          borderBottom: `1px solid ${T.slate200}`,
          backgroundColor: T.slate50,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Eye size={16} style={{ color: T.blue600 }} />
          <span style={{ fontSize: 14, fontWeight: 700, color: T.slate900 }}>
            {data?.batch?.batch_name ?? "Batch Details"}
          </span>
          {data?.batch && (
            <StatusBadge status={data.batch.status} />
          )}
        </div>
        <button
          onClick={onClose}
          aria-label="Close detail panel"
          style={{
            width: 28,
            height: 28,
            borderRadius: 6,
            border: `1px solid ${T.slate200}`,
            background: T.white,
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: T.slate500,
          }}
        >
          <X size={14} />
        </button>
      </div>

      {/* Tab strip */}
      <div
        style={{
          display: "flex",
          gap: 0,
          borderBottom: `1px solid ${T.slate200}`,
          backgroundColor: T.white,
          overflowX: "auto",
        }}
      >
        {tabs.map((t) => {
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
                padding: "11px 18px",
                fontSize: 13,
                fontWeight: active ? 700 : 500,
                color: active ? T.blue600 : T.slate500,
                background: "none",
                border: "none",
                borderBottom: active ? `2px solid ${T.blue600}` : "2px solid transparent",
                cursor: "pointer",
                whiteSpace: "nowrap",
                transition: "color 0.12s ease",
              }}
            >
              {t.icon}
              {t.label}
            </button>
          );
        })}
      </div>

      {/* Panel content */}
      <div style={{ padding: 20 }}>
        {isLoading && (
          <div style={{ textAlign: "center", padding: "40px 0", color: T.slate400 }}>
            <Loader2
              size={28}
              style={{ animation: "spin 1s linear infinite", margin: "0 auto" }}
            />
            <p style={{ marginTop: 12, fontSize: 13 }}>Loading batch details&hellip;</p>
          </div>
        )}

        {isError && (
          <div style={{ textAlign: "center", padding: "40px 0", color: T.red600 }}>
            <AlertTriangle size={28} style={{ margin: "0 auto" }} />
            <p style={{ marginTop: 10, fontSize: 13 }}>Failed to load batch details.</p>
          </div>
        )}

        {!isLoading && !isError && data && (
          <>
            {/* Claims Tab */}
            {tab === "claims" && (
              <div>
                {(data.claims ?? []).length === 0 ? (
                  <EmptyState
                    icon={<FileText size={24} />}
                    title="No claims records"
                    description="Process the batch to parse individual claim records."
                  />
                ) : (
                  <div
                    style={{
                      border: `1px solid ${T.slate200}`,
                      borderRadius: 10,
                      overflow: "hidden",
                    }}
                  >
                    {/* Header */}
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "2fr 1fr 1fr 2fr 90px",
                        padding: "8px 16px",
                        backgroundColor: T.slate50,
                        borderBottom: `1px solid ${T.slate200}`,
                        gap: 8,
                      }}
                    >
                      {["Patient", "DOS", "Provider", "Diagnoses", "Charges"].map(
                        (h) => (
                          <span
                            key={h}
                            style={{
                              fontSize: 11,
                              fontWeight: 600,
                              textTransform: "uppercase",
                              letterSpacing: "0.05em",
                              color: T.slate400,
                            }}
                          >
                            {h}
                          </span>
                        )
                      )}
                    </div>

                    {(data.claims ?? []).slice(0, 50).map((c, i) => (
                      <div
                        key={c.id}
                        style={{
                          display: "grid",
                          gridTemplateColumns: "2fr 1fr 1fr 2fr 90px",
                          padding: "10px 16px",
                          borderBottom:
                            i < (data.claims ?? []).length - 1
                              ? `1px solid ${T.slate100}`
                              : "none",
                          alignItems: "flex-start",
                          gap: 8,
                          backgroundColor: i % 2 === 1 ? T.slate50 : T.white,
                          transition: "background-color 0.12s ease",
                        }}
                        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = "#EFF6FF"; }}
                        onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = i % 2 === 1 ? T.slate50 : T.white; }}
                      >
                        <div>
                          <div
                            style={{
                              fontSize: 13,
                              fontWeight: 600,
                              color: T.slate800,
                            }}
                          >
                            {c.patient_name ?? "Unknown"}
                          </div>
                          {c.patient_id && (
                            <div
                              style={{
                                fontSize: 11,
                                color: T.slate400,
                                fontFamily: "monospace",
                              }}
                            >
                              {c.patient_id}
                            </div>
                          )}
                        </div>
                        <span style={{ fontSize: 12, color: T.slate600 }}>
                          {c.date_of_service}
                        </span>
                        <span
                          style={{
                            fontSize: 12,
                            color: T.slate600,
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {c.provider_name ?? "\u2014"}
                        </span>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                          {c.diagnoses.slice(0, 4).map((dx) => (
                            <span
                              key={dx}
                              style={{
                                padding: "2px 6px",
                                borderRadius: 4,
                                fontSize: 10,
                                fontFamily: "monospace",
                                fontWeight: 600,
                                backgroundColor: c.hcc_mapped
                                  ? T.blue50
                                  : T.slate100,
                                color: c.hcc_mapped ? T.blue700 : T.slate600,
                                border: `1px solid ${c.hcc_mapped ? T.blue100 : T.slate200}`,
                              }}
                            >
                              {dx}
                            </span>
                          ))}
                          {c.diagnoses.length > 4 && (
                            <span
                              style={{
                                fontSize: 10,
                                color: T.slate400,
                                alignSelf: "center",
                              }}
                            >
                              +{c.diagnoses.length - 4} more
                            </span>
                          )}
                        </div>
                        <span
                          className="tabular-nums"
                          style={{
                            fontSize: 12,
                            fontWeight: 600,
                            color: T.slate700,
                            textAlign: "right",
                            fontFamily: "monospace",
                          }}
                        >
                          ${c.charges.toLocaleString("en-US", { minimumFractionDigits: 2 })}
                        </span>
                      </div>
                    ))}

                    {(data.claims ?? []).length > 50 && (
                      <div
                        style={{
                          padding: "10px 16px",
                          textAlign: "center",
                          fontSize: 12,
                          color: T.slate500,
                          backgroundColor: T.slate50,
                          borderTop: `1px solid ${T.slate200}`,
                        }}
                      >
                        Showing 50 of {(data.claims ?? []).length} claims
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Diagnoses Tab */}
            {tab === "diagnoses" && (
              <div>
                {(data.diagnoses ?? []).length === 0 ? (
                  <EmptyState
                    icon={<Tag size={24} />}
                    title="No diagnosis records"
                    description="Process the batch to extract ICD-10 codes."
                  />
                ) : (
                  <div
                    style={{
                      border: `1px solid ${T.slate200}`,
                      borderRadius: 10,
                      overflow: "hidden",
                    }}
                  >
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "120px 1fr 100px 80px",
                        padding: "8px 16px",
                        backgroundColor: T.slate50,
                        borderBottom: `1px solid ${T.slate200}`,
                        gap: 8,
                      }}
                    >
                      {["ICD-10", "Description", "HCC Mapping", "Count"].map(
                        (h) => (
                          <span
                            key={h}
                            style={{
                              fontSize: 11,
                              fontWeight: 600,
                              textTransform: "uppercase",
                              letterSpacing: "0.05em",
                              color: T.slate400,
                            }}
                          >
                            {h}
                          </span>
                        )
                      )}
                    </div>

                    {(data.diagnoses ?? []).map((dx, i) => (
                      <div
                        key={dx.icd10_code}
                        style={{
                          display: "grid",
                          gridTemplateColumns: "120px 1fr 100px 80px",
                          padding: "10px 16px",
                          borderBottom:
                            i < (data.diagnoses ?? []).length - 1
                              ? `1px solid ${T.slate100}`
                              : "none",
                          alignItems: "center",
                          gap: 8,
                          backgroundColor: i % 2 === 1 ? T.slate50 : T.white,
                          transition: "background-color 0.12s ease",
                        }}
                        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = "#EFF6FF"; }}
                        onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = i % 2 === 1 ? T.slate50 : T.white; }}
                      >
                        <span
                          style={{
                            fontSize: 12,
                            fontFamily: "monospace",
                            fontWeight: 700,
                            color: T.slate700,
                            padding: "3px 7px",
                            backgroundColor: T.slate100,
                            borderRadius: 5,
                            display: "inline-block",
                          }}
                        >
                          {dx.icd10_code}
                        </span>
                        <span
                          style={{
                            fontSize: 12,
                            color: T.slate600,
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {dx.description ?? "\u2014"}
                        </span>
                        {dx.hcc_code ? (
                          <span
                            style={{
                              fontSize: 11,
                              fontWeight: 600,
                              padding: "3px 8px",
                              borderRadius: 999,
                              backgroundColor: T.blue50,
                              color: T.blue700,
                              border: `1px solid ${T.blue100}`,
                              display: "inline-block",
                            }}
                          >
                            HCC {dx.hcc_code}
                          </span>
                        ) : (
                          <span
                            style={{
                              fontSize: 11,
                              fontWeight: 600,
                              padding: "3px 8px",
                              borderRadius: 999,
                              backgroundColor: T.gray100,
                              color: T.gray400,
                              display: "inline-block",
                            }}
                          >
                            Unmapped
                          </span>
                        )}
                        <span
                          style={{
                            fontSize: 12,
                            fontWeight: 600,
                            color: T.slate700,
                          }}
                        >
                          {dx.count}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* HCC Summary Tab */}
            {tab === "hcc" && (
              <div>
                <p
                  style={{
                    margin: "0 0 16px",
                    fontSize: 13,
                    color: T.slate500,
                  }}
                >
                  Distribution of HCC codes found in this batch (top 10 by
                  patient count).
                </p>
                <HccBarChart items={data.hcc_summary} />
              </div>
            )}

            {/* Unmapped Patients Tab */}
            {tab === "unmapped" && (
              <div>
                {(data.unmapped_patients ?? []).length === 0 ? (
                  <EmptyState
                    icon={<CheckCircle size={24} />}
                    title="All patients matched"
                    description="Every patient in this batch has been linked to an OpenEMR record."
                  />
                ) : (
                  <div>
                    <p
                      style={{
                        margin: "0 0 14px",
                        fontSize: 13,
                        color: T.slate500,
                      }}
                    >
                      {(data.unmapped_patients ?? []).length} patient
                      {(data.unmapped_patients ?? []).length !== 1 ? "s" : ""} in this
                      batch could not be automatically matched to OpenEMR
                      records.
                    </p>
                    <div
                      style={{
                        border: `1px solid ${T.slate200}`,
                        borderRadius: 10,
                        overflow: "hidden",
                      }}
                    >
                      <div
                        style={{
                          display: "grid",
                          gridTemplateColumns: "1fr 1fr 80px 140px",
                          padding: "8px 16px",
                          backgroundColor: T.slate50,
                          borderBottom: `1px solid ${T.slate200}`,
                          gap: 8,
                        }}
                      >
                        {["Patient ID", "Name", "Claims", "Action"].map(
                          (h) => (
                            <span
                              key={h}
                              style={{
                                fontSize: 11,
                                fontWeight: 600,
                                textTransform: "uppercase",
                                letterSpacing: "0.05em",
                                color: T.slate400,
                              }}
                            >
                              {h}
                            </span>
                          )
                        )}
                      </div>

                      {(data.unmapped_patients ?? []).map((pt, i) => (
                        <div
                          key={pt.claim_patient_id}
                          style={{
                            display: "grid",
                            gridTemplateColumns: "1fr 1fr 80px 140px",
                            padding: "10px 16px",
                            borderBottom:
                              i < (data.unmapped_patients ?? []).length - 1
                                ? `1px solid ${T.slate100}`
                                : "none",
                            alignItems: "center",
                            gap: 8,
                          }}
                        >
                          <span
                            style={{
                              fontSize: 12,
                              fontFamily: "monospace",
                              color: T.slate600,
                            }}
                          >
                            {pt.claim_patient_id}
                          </span>
                          <span style={{ fontSize: 13, color: T.slate700 }}>
                            {pt.patient_name ?? "\u2014"}
                          </span>
                          <span
                            style={{
                              fontSize: 12,
                              fontWeight: 600,
                              color: T.slate600,
                            }}
                          >
                            {pt.claim_count}
                          </span>
                          <button
                            onClick={() =>
                              mapMut.mutate(pt.claim_patient_id)
                            }
                            disabled={mapMut.isPending}
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              gap: 5,
                              padding: "5px 10px",
                              borderRadius: 7,
                              border: `1px solid ${T.blue600}`,
                              backgroundColor: "transparent",
                              color: T.blue600,
                              fontSize: 12,
                              fontWeight: 600,
                              cursor: mapMut.isPending
                                ? "not-allowed"
                                : "pointer",
                              opacity: mapMut.isPending ? 0.5 : 1,
                              transition: "all 0.12s ease",
                            }}
                          >
                            <Link2 size={11} />
                            Map to OpenEMR
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
// Delete Confirm Dialog
// ─────────────────────────────────────────────

function ConfirmDeleteDialog({
  batchName,
  onConfirm,
  onCancel,
  isPending,
}: {
  batchName: string;
  onConfirm: () => void;
  onCancel: () => void;
  isPending: boolean;
}) {
  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        backgroundColor: "rgba(15, 23, 42, 0.55)",
        zIndex: 110,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onCancel(); }}
      role="dialog"
      aria-modal="true"
      aria-label="Confirm delete"
    >
      <div
        className="animate-scale-in"
        style={{
          backgroundColor: T.white,
          borderRadius: 14,
          width: "100%",
          maxWidth: 420,
          padding: 28,
          boxShadow: "0 20px 50px rgba(0,0,0,0.18)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          style={{
            width: 48,
            height: 48,
            borderRadius: 14,
            backgroundColor: T.red50,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: T.red600,
            marginBottom: 16,
          }}
        >
          <Trash2 size={22} />
        </div>
        <h3 style={{ margin: "0 0 8px", fontSize: 17, fontWeight: 700, color: T.slate900 }}>
          Delete Batch?
        </h3>
        <p style={{ margin: "0 0 24px", fontSize: 13, color: T.slate500, lineHeight: 1.6 }}>
          <strong style={{ color: T.slate700 }}>&ldquo;{batchName}&rdquo;</strong> and
          all associated claims data will be permanently deleted. This cannot be undone.
        </p>
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <button
            onClick={onCancel}
            disabled={isPending}
            style={{
              height: 38,
              padding: "0 18px",
              borderRadius: 8,
              border: `1px solid ${T.slate200}`,
              backgroundColor: T.white,
              fontSize: 13,
              fontWeight: 500,
              color: T.slate600,
              cursor: isPending ? "not-allowed" : "pointer",
            }}
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={isPending}
            style={{
              height: 38,
              padding: "0 18px",
              borderRadius: 8,
              border: "none",
              backgroundColor: T.red600,
              fontSize: 13,
              fontWeight: 600,
              color: T.white,
              cursor: isPending ? "not-allowed" : "pointer",
              opacity: isPending ? 0.6 : 1,
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            {isPending ? (
              <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} />
            ) : (
              <Trash2 size={13} />
            )}
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
// Main Page
// ─────────────────────────────────────────────

export default function ClaimsPage() {
  const queryClient = useQueryClient();

  const [showUpload, setShowUpload] = useState(false);
  const [expandedBatchId, setExpandedBatchId] = useState<number | null>(null);
  const [deletingBatch, setDeletingBatch] = useState<ClaimsBatch | null>(null);
  const [page, setPage] = useState(0);
  const [hoveredRow, setHoveredRow] = useState<number | null>(null);

  /* --- Queries ---- */

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ["claims-stats"],
    queryFn: fetchClaimsStats,
    refetchInterval: 15_000,
  });

  const {
    data: batches = [],
    isLoading: batchesLoading,
    isError: batchesError,
    refetch: refetchBatches,
  } = useQuery({
    queryKey: ["claims-batches"],
    queryFn: fetchBatches,
    refetchInterval: 10_000,
  });

  /* --- Mutations --- */

  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteBatch(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["claims-batches"] });
      queryClient.invalidateQueries({ queryKey: ["claims-stats"] });
      setDeletingBatch(null);
      if (expandedBatchId === deletingBatch?.id) setExpandedBatchId(null);
    },
  });

  const processMut = useMutation({
    mutationFn: (id: number) => processBatch(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["claims-batches"] });
      queryClient.invalidateQueries({ queryKey: ["claims-stats"] });
    },
  });

  const rafMut = useMutation({
    mutationFn: (id: number) => calculateRAF(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["claims-batches"] });
      queryClient.invalidateQueries({ queryKey: ["claims-stats"] });
    },
  });

  /* --- Pagination --- */

  const totalPages = Math.max(1, Math.ceil(batches.length / PAGE_SIZE));
  const pagedBatches = batches.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  /* --- Helpers --- */

  const handleUploadSuccess = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["claims-batches"] });
    queryClient.invalidateQueries({ queryKey: ["claims-stats"] });
  }, [queryClient]);

  const toggleDetail = useCallback((id: number) => {
    setExpandedBatchId((prev) => (prev === id ? null : id));
  }, []);

  const formatDate = (iso: string) => {
    try {
      return new Date(iso).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
    } catch {
      return iso;
    }
  };

  /* --- Error state --- */

  if (batchesError) {
    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          height: "60vh",
          gap: 16,
        }}
      >
        <div
          style={{
            borderRadius: 16,
            backgroundColor: T.red50,
            padding: 20,
          }}
        >
          <AlertTriangle size={40} color={T.red500} />
        </div>
        <h2
          style={{ fontSize: 18, fontWeight: 700, color: T.slate900, margin: 0 }}
        >
          Failed to load claims data
        </h2>
        <p style={{ fontSize: 14, color: T.slate500, margin: 0 }}>
          Check that the server is running and try again.
        </p>
        <button
          onClick={() => refetchBatches()}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            borderRadius: 8,
            border: `1px solid ${T.slate200}`,
            backgroundColor: T.white,
            padding: "8px 16px",
            fontSize: 14,
            fontWeight: 500,
            color: T.slate600,
            cursor: "pointer",
          }}
        >
          <RefreshCw size={16} /> Retry
        </button>
      </div>
    );
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 0,
        fontFamily:
          "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
      }}
    >
      {/* Keyframes */}
      <style>{`
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        @keyframes dash-march { to { stroke-dashoffset: -20; } }
      `}</style>

      {/* ── Page Header ──────────────────────────────────── */}
      <PageHeader
        title="Claims Data"
        icon={<FileText size={22} />}
        subtitle={
          !batchesLoading
            ? `${batches.length.toLocaleString()} batch${batches.length !== 1 ? "es" : ""} loaded`
            : undefined
        }
        actions={
          <button
            className="btn-press"
            onClick={() => setShowUpload(true)}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 7,
              height: 40,
              padding: "0 20px",
              borderRadius: 10,
              border: "none",
              background: "linear-gradient(135deg, #2563EB 0%, #1D4ED8 100%)",
              color: T.white,
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
              transition: "all 0.15s ease",
              boxShadow: "0 2px 8px rgba(37,99,235,0.35), 0 1px 2px rgba(37,99,235,0.2)",
            }}
            aria-label="Upload Claims"
          >
            <Upload size={15} />
            Upload Claims
          </button>
        }
      />

      {/* ── Stats Row ────────────────────────────────────── */}
      {statsLoading ? (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 24 }}>
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className={`premium-card shimmer stagger-${i + 1}`} style={{ padding: 20 }}>
              <div className="skeleton" style={{ width: 90, height: 12, borderRadius: 4, marginBottom: 10 }} />
              <div className="skeleton" style={{ width: 64, height: 28, borderRadius: 4, marginBottom: 8 }} />
              <div className="skeleton" style={{ width: 110, height: 10, borderRadius: 4 }} />
            </div>
          ))}
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(4, 1fr)",
            gap: 16,
            marginBottom: 24,
          }}
        >
          <div className="animate-fade-in stagger-1 hover-lift">
            <StatCard
              label="Total Batches"
              value={stats?.total_batches ?? 0}
              icon={<FileText size={18} />}
              color={T.blue600}
            />
          </div>
          <div className="animate-fade-in stagger-2 hover-lift">
            <StatCard
              label="Claims Processed"
              value={(stats?.total_claims ?? 0).toLocaleString()}
              icon={<CheckCircle size={18} />}
              color={T.emerald600}
            />
          </div>
          <div className="animate-fade-in stagger-3 hover-lift">
            <StatCard
              label="Patients Matched"
              value={(stats?.total_matched_patients ?? 0).toLocaleString()}
              icon={<User size={18} />}
              color={T.amber600}
            />
          </div>
          <div className="animate-fade-in stagger-4 hover-lift">
            <StatCard
              label="HCC Codes Found"
              value={(stats?.unique_hcc_codes ?? 0).toLocaleString()}
              icon={<Tag size={18} />}
              color={T.violet500}
            />
          </div>
        </div>
      )}

      {/* ── Batches Table ────────────────────────────────── */}
      <div
        className="premium-card animate-slide-up"
        style={{
          overflow: "hidden",
        }}
      >
        {/* Column header */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "2fr 90px 200px 110px 110px 160px",
            alignItems: "center",
            padding: "12px 16px 12px 20px",
            background: "linear-gradient(135deg, #F8FAFC 0%, #F1F5F9 100%)",
            borderBottom: `2px solid ${T.slate200}`,
            gap: 8,
          }}
        >
          {[
            "Batch Name",
            "File Type",
            "Claims",
            "Status",
            "Uploaded",
            "Actions",
          ].map((h) => (
            <span
              key={h}
              style={{
                fontSize: 11,
                fontWeight: 700,
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                color: T.slate500,
              }}
            >
              {h}
            </span>
          ))}
        </div>

        {/* Loading skeleton */}
        {batchesLoading &&
          Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className={`stagger-${Math.min(i + 1, 6)}`}
              style={{
                display: "grid",
                gridTemplateColumns: "2fr 90px 200px 110px 110px 160px",
                alignItems: "center",
                padding: "0 16px 0 20px",
                height: 60,
                borderBottom: `1px solid ${T.slate100}`,
                gap: 8,
              }}
            >
              {[180, 60, 140, 80, 80, 120].map((w, j) => (
                <div
                  key={j}
                  className="skeleton shimmer"
                  style={{
                    width: w,
                    height: 12,
                    borderRadius: 4,
                  }}
                />
              ))}
            </div>
          ))}

        {/* Empty state */}
        {!batchesLoading && batches.length === 0 && (
          <EmptyState
            icon={<FileSearch size={24} />}
            title="No claims batches yet"
            description="Upload a claims file to get started with claims processing and HCC mapping."
          />
        )}

        {/* Batch rows */}
        {!batchesLoading &&
          pagedBatches.map((batch) => {
            const isExpanded = expandedBatchId === batch.id;
            const isHovered = hoveredRow === batch.id;
            const isProcessRunning =
              processMut.isPending || rafMut.isPending;

            const totalClaims = batch.total_claims;
            const processed = batch.processed_claims;
            const failed = batch.failed_claims;
            const pct =
              totalClaims > 0 ? Math.round((processed / totalClaims) * 100) : 0;

            return (
              <React.Fragment key={batch.id}>
                {/* Row */}
                <div
                  onMouseEnter={() => setHoveredRow(batch.id)}
                  onMouseLeave={() => setHoveredRow(null)}
                  className="animate-fade-in"
                  style={{
                    display: "grid",
                    gridTemplateColumns: "2fr 90px 200px 110px 110px 160px",
                    alignItems: "center",
                    padding: "0 16px 0 20px",
                    height: 60,
                    borderBottom: isExpanded
                      ? `1px solid ${T.blue100}`
                      : `1px solid ${T.slate100}`,
                    backgroundColor: isExpanded
                      ? T.blue50
                      : isHovered
                      ? "#EFF6FF"
                      : pagedBatches.indexOf(batch) % 2 === 1
                      ? T.slate50
                      : T.white,
                    gap: 8,
                    transition: "all 0.15s ease",
                    ...(isHovered && !isExpanded ? { boxShadow: "inset 3px 0 0 0 #3B82F6" } : {}),
                  }}
                >
                  {/* Batch Name */}
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      cursor: "pointer",
                      minWidth: 0,
                    }}
                    onClick={() => toggleDetail(batch.id)}
                    role="button"
                    tabIndex={0}
                    aria-expanded={isExpanded}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ")
                        toggleDetail(batch.id);
                    }}
                  >
                    <div
                      style={{
                        width: 32,
                        height: 32,
                        borderRadius: 8,
                        backgroundColor: `${T.blue600}1A`,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        color: T.blue600,
                        flexShrink: 0,
                      }}
                    >
                      <FileText size={15} />
                    </div>
                    <div style={{ minWidth: 0 }}>
                      <div
                        style={{
                          fontSize: 13,
                          fontWeight: 600,
                          color: T.slate900,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {batch.batch_name}
                      </div>
                      <div
                        style={{
                          fontSize: 11,
                          color: T.slate400,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {batch.file_name}
                      </div>
                    </div>
                    <div style={{ flexShrink: 0, color: T.slate400 }}>
                      {isExpanded ? (
                        <ChevronUp size={14} />
                      ) : (
                        <ChevronDown size={14} />
                      )}
                    </div>
                  </div>

                  {/* File Type */}
                  <span
                    style={{
                      fontSize: 11,
                      fontWeight: 700,
                      padding: "3px 8px",
                      borderRadius: 5,
                      backgroundColor: T.slate100,
                      color: T.slate600,
                      fontFamily: "monospace",
                      display: "inline-block",
                    }}
                  >
                    {fileTypeLabel(batch.file_type)}
                  </span>

                  {/* Claims progress */}
                  <div>
                    <div
                      className="tabular-nums"
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        fontSize: 11,
                        color: T.slate500,
                        marginBottom: 4,
                      }}
                    >
                      <span>
                        <strong style={{ color: T.slate700 }}>
                          {processed.toLocaleString()}
                        </strong>
                        /{totalClaims.toLocaleString()}
                      </span>
                      {failed > 0 && (
                        <span style={{ color: T.red600, fontWeight: 600 }}>
                          {failed} failed
                        </span>
                      )}
                    </div>
                    <div
                      style={{
                        height: 5,
                        borderRadius: 3,
                        backgroundColor: T.slate100,
                        overflow: "hidden",
                      }}
                    >
                      <div
                        style={{
                          height: "100%",
                          width: `${pct}%`,
                          borderRadius: 3,
                          backgroundColor:
                            batch.status === "failed"
                              ? T.red500
                              : batch.status === "completed"
                              ? T.emerald500
                              : T.blue500,
                          transition: "width 0.3s ease",
                        }}
                      />
                    </div>
                  </div>

                  {/* Status */}
                  <StatusBadge status={batch.status} />

                  {/* Uploaded date */}
                  <span style={{ fontSize: 12, color: T.slate500 }}>
                    {formatDate(batch.created_at)}
                  </span>

                  {/* Actions */}
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 4,
                    }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    {/* View Details */}
                    <button
                      onClick={() => toggleDetail(batch.id)}
                      title="View Details"
                      aria-label="View batch details"
                      style={actionBtnStyle(isExpanded ? T.blue600 : undefined)}
                    >
                      <Eye size={13} />
                    </button>

                    {/* Process */}
                    {(batch.status === "uploaded" ||
                      batch.status === "failed") && (
                      <button
                        onClick={() => processMut.mutate(batch.id)}
                        disabled={isProcessRunning}
                        title="Process Batch"
                        aria-label="Process batch"
                        style={actionBtnStyle(T.emerald600)}
                      >
                        <Play size={13} />
                      </button>
                    )}

                    {/* Calculate RAF */}
                    {batch.status === "completed" && (
                      <button
                        onClick={() => rafMut.mutate(batch.id)}
                        disabled={isProcessRunning}
                        title="Calculate RAF"
                        aria-label="Calculate RAF scores"
                        style={actionBtnStyle(T.amber600)}
                      >
                        <Calculator size={13} />
                      </button>
                    )}

                    {/* Delete */}
                    <button
                      onClick={() => setDeletingBatch(batch)}
                      title="Delete Batch"
                      aria-label="Delete batch"
                      style={actionBtnStyle(T.red600)}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>

                {/* Expanded Detail */}
                {isExpanded && (
                  <div
                    style={{
                      padding: "0 20px 20px",
                      backgroundColor: T.blue50,
                      borderBottom: `1px solid ${T.slate200}`,
                    }}
                  >
                    <BatchDetailPanel
                      batchId={batch.id}
                      onClose={() => setExpandedBatchId(null)}
                      onMapSuccess={() => {
                        queryClient.invalidateQueries({
                          queryKey: ["claims-stats"],
                        });
                      }}
                    />
                  </div>
                )}
              </React.Fragment>
            );
          })}

        {/* Pagination */}
        {!batchesLoading && totalPages > 1 && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 16,
              padding: "14px 20px",
              borderTop: `1px solid ${T.slate200}`,
              backgroundColor: T.slate50,
            }}
          >
            <button
              disabled={page === 0}
              onClick={() => setPage((p) => p - 1)}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                padding: "6px 14px",
                borderRadius: 8,
                border: `1px solid ${T.slate200}`,
                backgroundColor: T.white,
                fontSize: 13,
                fontWeight: 500,
                color: page === 0 ? T.slate300 : T.slate600,
                cursor: page === 0 ? "not-allowed" : "pointer",
                opacity: page === 0 ? 0.5 : 1,
              }}
              aria-label="Previous page"
            >
              <ChevronLeft size={14} /> Previous
            </button>

            <span className="tabular-nums" style={{ fontSize: 13, color: T.slate500 }}>
              Page{" "}
              <strong style={{ color: T.slate900 }}>{page + 1}</strong> of{" "}
              <strong style={{ color: T.slate900 }}>{totalPages}</strong>
            </span>

            <button
              disabled={page >= totalPages - 1}
              onClick={() => setPage((p) => p + 1)}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                padding: "6px 14px",
                borderRadius: 8,
                border: `1px solid ${T.slate200}`,
                backgroundColor: T.white,
                fontSize: 13,
                fontWeight: 500,
                color: page >= totalPages - 1 ? T.slate300 : T.slate600,
                cursor: page >= totalPages - 1 ? "not-allowed" : "pointer",
                opacity: page >= totalPages - 1 ? 0.5 : 1,
              }}
              aria-label="Next page"
            >
              Next <ChevronRight size={14} />
            </button>
          </div>
        )}
      </div>

      {/* ── Upload Dialog ────────────────────────────────── */}
      {showUpload && (
        <UploadDialog
          onClose={() => setShowUpload(false)}
          onSuccess={handleUploadSuccess}
        />
      )}

      {/* ── Delete Confirm ───────────────────────────────── */}
      {deletingBatch && (
        <ConfirmDeleteDialog
          batchName={deletingBatch.batch_name}
          isPending={deleteMut.isPending}
          onConfirm={() => deleteMut.mutate(deletingBatch.id)}
          onCancel={() => setDeletingBatch(null)}
        />
      )}
    </div>
  );
}

// ─────────────────────────────────────────────
// Action button style helper
// ─────────────────────────────────────────────

function actionBtnStyle(accentColor?: string): React.CSSProperties {
  return {
    width: 30,
    height: 30,
    borderRadius: 7,
    border: `1px solid ${accentColor ? `${accentColor}30` : "#E2E8F0"}`,
    backgroundColor: accentColor ? `${accentColor}0D` : "#F8FAFC",
    color: accentColor ?? "#64748B",
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    transition: "all 0.15s ease",
    flexShrink: 0,
    boxShadow: accentColor ? `0 1px 3px ${accentColor}15` : "none",
  };
}
