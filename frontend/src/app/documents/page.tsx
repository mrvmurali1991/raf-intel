"use client";

import { ErrorBoundary } from "@/components/error-boundary";
import React, {
  useState,
  useRef,
  useCallback,
  useEffect,
  useMemo,
} from "react";
import {
  FileImage,
  Upload,
  Search,
  X,
  Eye,
  Trash2,
  Zap,
  ChevronLeft,
  ChevronRight,
  FileText,
  Image as ImageIcon,
  AlertCircle,
  CheckCircle2,
  Clock,
  Link2,
  ChevronDown,
  Download,
  RefreshCw,
  Database,
} from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import NextImage from "next/image";
import api from "@/lib/api";
import {
  PageHeader,
  ProgressBar,
  EmptyState,
  ConfidencePill,
  MeatIndicator,
  DataRow,
} from "@/components/healthcare-ui";
import { MetricCard } from "@/components/ui/metric-card";
import { searchPatients } from "@/lib/api";
import { tokens } from "@/styles/tokens";

// ─── Axios instance with baseURL ──────────────────────────────────────────────

// ─── Design Tokens ────────────────────────────────────────────────────────────

const c = {
  primary: tokens.primary,
  primaryHover: tokens.primaryDark,
  white: tokens.white,
  slate900: tokens.slate900,
  slate700: tokens.slate700,
  slate600: tokens.slate600,
  slate400: tokens.slate400,
  slate200: tokens.slate200,
  slate100: tokens.slate100,
  slate50: tokens.slate50,
  red600: tokens.riskHigh,
  red50: tokens.riskHighSoft,
  emerald600: tokens.riskLow,
  emerald500: tokens.success,
  emerald50: tokens.successSoft,
  amber500: tokens.warningStrong,
  amber50: tokens.warningSoft,
  blue500: tokens.infoBlue,
  blue50: tokens.primarySoft,
  violet500: tokens.accentPurple,
  violet50: tokens.primarySoft,
  subtleText: tokens.slate500,
  border: tokens.slate200,
};

// ─── Types ────────────────────────────────────────────────────────────────────

type DocumentStatus = "uploaded" | "processing" | "analyzed" | "reviewed" | "error";

type DocumentType =
  | "Progress Note"
  | "Discharge Summary"
  | "Lab Report"
  | "Radiology Report"
  | "Consultation"
  | "Operative Note"
  | "Pathology"
  | "Referral"
  | "Other";

interface FileUploadItem {
  id: string;
  file: File;
  patientId: string;
  patientName: string;
  documentType: DocumentType;
  encounterDate: string;
  progress: number;
  status: "pending" | "uploading" | "done" | "error";
  error?: string;
  previewUrl?: string;
}

interface Document {
  id: string;
  filename: string;
  document_type: DocumentType;
  patient_name: string;
  patient_id: string;
  encounter_date: string;
  status: DocumentStatus;
  hcc_count: number;
  file_type: string;
  file_size: number;
  page_count?: number;
  upload_date: string;
  processing_time_ms?: number;
  tokens_used?: number;
  extracted_text?: string;
  analysis_results?: AnalysisResults;
}

interface DiagnosisResult {
  icd10_code: string;
  description: string;
  hcc_category?: string;
  hcc_number?: number;
  confidence: number;
  page_number?: number;
  evidence_text?: string;
  confirmed?: boolean | null;
}

interface MedicationResult {
  name: string;
  dose?: string;
  frequency?: string;
  route?: string;
}

interface LabResult {
  name: string;
  value: string;
  unit?: string;
  reference_range?: string;
  flag?: "high" | "low" | "normal";
}

interface MeatEvidence {
  M?: string;
  E?: string;
  A?: string;
  T?: string;
}

interface AnalysisResults {
  diagnoses: DiagnosisResult[];
  medications: MedicationResult[];
  labs: LabResult[];
  clinical_summary?: string;
  meat_evidence?: MeatEvidence;
  raw_text?: string;
}

type AnalysisTab = "diagnoses" | "medications" | "labs" | "summary" | "meat" | "raw";

const DOCUMENT_TYPES: DocumentType[] = [
  "Progress Note",
  "Discharge Summary",
  "Lab Report",
  "Radiology Report",
  "Consultation",
  "Operative Note",
  "Pathology",
  "Referral",
  "Other",
];

const ACCEPTED_TYPES =
  ".pdf,.png,.jpg,.jpeg,.tiff,.bmp,.gif,.webp,.heic";

const PAGE_SIZE = 15;

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(s: string): string {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return s;
  }
}

function statusConfig(status: DocumentStatus) {
  switch (status) {
    case "uploaded":
      return { label: "Uploaded", bg: tokens.slate100, color: tokens.slate600, pulse: false };
    case "processing":
      return { label: "Processing", bg: tokens.primarySoft, color: tokens.primary, pulse: true };
    case "analyzed":
      return { label: "Analyzed", bg: tokens.successSoft, color: tokens.riskLow, pulse: false };
    case "reviewed":
      return { label: "Reviewed", bg: tokens.emerald100, color: tokens.emerald800, pulse: false };
    case "error":
      return { label: "Error", bg: tokens.riskHighSoft, color: tokens.riskHigh, pulse: false };
    default:
      return { label: status as string, bg: tokens.slate100, color: tokens.slate500, pulse: false };
  }
}

function fileIcon(fileType: string) {
  if (fileType?.includes("pdf")) return <FileText size={16} color={c.red600} strokeWidth={2.2} />;
  if (fileType?.includes("tiff") || fileType?.includes("bmp")) return <ImageIcon size={16} color={c.violet500} strokeWidth={2.2} />;
  return <ImageIcon size={16} color={c.blue500} strokeWidth={2.2} />;
}

// ─── API Calls ────────────────────────────────────────────────────────────────

async function fetchDocuments(params: {
  status?: string;
  document_type?: string;
  patient_id?: string;
  date_from?: string;
  date_to?: string;
  page: number;
}) {
  const p: Record<string, string> = { limit: String(PAGE_SIZE), offset: String(params.page * PAGE_SIZE) };
  if (params.status) p.status = params.status;
  if (params.document_type) p.document_type = params.document_type;
  if (params.patient_id) p.patient_id = params.patient_id;
  if (params.date_from) p.date_from = params.date_from;
  if (params.date_to) p.date_to = params.date_to;
  const qs = new URLSearchParams(p).toString();
  const res = await api.get(`/api/documents?${qs}`);
  return res.data as { documents: Document[]; total: number; stats: { total: number; analyzed: number; hcc_count: number; pending: number } };
}

async function analyzeDocument(id: string) {
  const res = await api.post(`/api/documents/${id}/analyze`);
  return res.data;
}

async function deleteDocument(id: string) {
  await api.delete(`/api/documents/${id}`);
}

async function confirmDiagnosis(docId: string, icd10: string, confirmed: boolean) {
  const res = await api.patch(`/api/documents/${docId}/diagnoses/${encodeURIComponent(icd10)}`, { confirmed });
  return res.data;
}


// ─── Upload Zone ──────────────────────────────────────────────────────────────

interface UploadPanelProps {
  onClose: () => void;
  onUploaded: () => void;
}

function UploadPanel({ onClose, onUploaded }: UploadPanelProps) {
  const [items, setItems] = useState<FileUploadItem[]>([]);
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [patientSearch, setPatientSearch] = useState("");
  const [patientSearchDebounced, setPatientSearchDebounced] = useState("");

  useEffect(() => {
    const t = setTimeout(() => setPatientSearchDebounced(patientSearch), 350);
    return () => clearTimeout(t);
  }, [patientSearch]);

  const { data: patientData } = useQuery({
    queryKey: ["patients-search", patientSearchDebounced],
    queryFn: () => searchPatients({ search: patientSearchDebounced || undefined, limit: 20 }),
    enabled: patientSearchDebounced.length > 1,
  });
  const patients = patientData?.patients ?? [];

  const addFiles = useCallback(
    (files: FileList | File[]) => {
      const arr = Array.from(files);
      const newItems: FileUploadItem[] = arr.map((f) => ({
        id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
        file: f,
        patientId: "",
        patientName: "",
        documentType: "Progress Note",
        encounterDate: new Date().toISOString().slice(0, 10),
        progress: 0,
        status: "pending",
        previewUrl: f.type.startsWith("image/") ? URL.createObjectURL(f) : undefined,
      }));
      setItems((prev) => [...prev, ...newItems]);
    },
    []
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
      if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
    },
    [addFiles]
  );

  const removeItem = useCallback((id: string) => {
    setItems((prev) => {
      const item = prev.find((i) => i.id === id);
      if (item?.previewUrl) URL.revokeObjectURL(item.previewUrl);
      return prev.filter((i) => i.id !== id);
    });
  }, []);

  const updateItem = useCallback((id: string, patch: Partial<FileUploadItem>) => {
    setItems((prev) => prev.map((i) => (i.id === id ? { ...i, ...patch } : i)));
  }, []);

  const uploadAll = useCallback(async () => {
    const pending = items.filter((i) => i.status === "pending");
    for (const item of pending) {
      updateItem(item.id, { status: "uploading", progress: 0 });
      const fd = new FormData();
      fd.append("file", item.file);
      if (item.patientId) fd.append("patient_id", item.patientId);
      fd.append("document_type", item.documentType);
      fd.append("encounter_date", item.encounterDate);
      try {
        await api.post("/api/documents/upload", fd, {
          onUploadProgress: (e) => {
            const pct = e.total ? Math.round((e.loaded / e.total) * 100) : 0;
            updateItem(item.id, { progress: pct });
          },
        });
        updateItem(item.id, { status: "done", progress: 100 });
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Upload failed";
        updateItem(item.id, { status: "error", error: msg });
      }
    }
    onUploaded();
  }, [items, updateItem, onUploaded]);

  const hasPending = items.some((i) => i.status === "pending");
  const allDone = items.length > 0 && items.every((i) => i.status === "done");

  return (
    <div
      className="premium-card animate-slide-up"
      style={{
        marginBottom: 24,
        overflow: "hidden",
      }}
    >
      {/* Panel Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "16px 24px",
          borderBottom: `1px solid ${c.slate100}`,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: 8,
              background: `${c.primary}1A`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <Upload size={16} color={c.primary} />
          </div>
          <span style={{ fontSize: 15, fontWeight: 700, color: c.slate900 }}>
            Upload Clinical Documents
          </span>
        </div>
        <button
          onClick={onClose}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            color: c.slate400,
            display: "flex",
            alignItems: "center",
            padding: 4,
            borderRadius: 6,
          }}
          aria-label="Close upload panel"
        >
          <X size={18} />
        </button>
      </div>

      <div style={{ padding: 24 }}>
        {/* Drop Zone */}
        <div
          onDragOver={(e) => { e.preventDefault(); setIsDragOver(true); }}
          onDragLeave={() => setIsDragOver(false)}
          onDrop={onDrop}
          onClick={() => fileInputRef.current?.click()}
          role="button"
          tabIndex={0}
          aria-label="Drop files here or click to browse"
          onKeyDown={(e) => e.key === "Enter" && fileInputRef.current?.click()}
          className={isDragOver ? "card-glow-blue" : ""}
          style={{
            border: `2px dashed ${isDragOver ? c.primary : c.slate200}`,
            borderRadius: 14,
            padding: "48px 24px",
            textAlign: "center",
            cursor: "pointer",
            background: isDragOver ? `${c.primary}08` : `linear-gradient(135deg, ${c.slate50} 0%, ${tokens.primarySoft} 100%)`,
            transition: "all 0.3s cubic-bezier(0.4, 0, 0.2, 1)",
            marginBottom: items.length ? 24 : 0,
            position: "relative",
            overflow: "hidden",
            backgroundImage: isDragOver ? undefined : `url("data:image/svg+xml,%3csvg width='100%25' height='100%25' xmlns='http://www.w3.org/2000/svg'%3e%3crect width='100%25' height='100%25' fill='none' rx='16' ry='16' stroke='%2394A3B8' stroke-width='2' stroke-dasharray='8%2c 6' stroke-dashoffset='0' stroke-linecap='round'/%3e%3c/svg%3e")`,
            borderColor: isDragOver ? c.primary : "transparent",
          }}
        >
          <div
            className={isDragOver ? "soft-pulse" : ""}
            style={{
              width: 64,
              height: 64,
              borderRadius: 14,
              background: isDragOver ? `${c.primary}1A` : `linear-gradient(135deg, ${c.primary}15 0%, ${c.primary}08 100%)`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              margin: "0 auto 16px",
              transition: "all 0.3s cubic-bezier(0.4, 0, 0.2, 1)",
              transform: isDragOver ? "scale(1.1)" : "scale(1)",
              boxShadow: isDragOver ? `0 8px 24px ${c.primary}20` : "none",
            }}
          >
            <Upload
              size={26}
              color={isDragOver ? c.primary : c.slate400}
              style={{
                transition: "all 0.3s ease",
                transform: isDragOver ? "translateY(-3px)" : "translateY(0)",
              }}
            />
          </div>
          <p style={{ margin: "0 0 6px", fontSize: 16, fontWeight: 700, color: isDragOver ? c.primary : c.slate900 }}>
            {isDragOver ? "Release to add files" : "Drop files here, or click to browse"}
          </p>
          <p style={{ margin: 0, fontSize: 13, color: c.subtleText }}>
            Supports PDF, PNG, JPG, JPEG, TIFF, BMP, GIF, WEBP, HEIC
          </p>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ACCEPTED_TYPES}
            style={{ display: "none" }}
            onChange={(e) => e.target.files && addFiles(e.target.files)}
            aria-hidden="true"
          />
        </div>

        {/* File Items */}
        {items.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {items.map((item) => (
              <FileItemRow
                key={item.id}
                item={item}
                patients={patients}
                patientSearch={patientSearch}
                onPatientSearch={setPatientSearch}
                onUpdate={updateItem}
                onRemove={removeItem}
              />
            ))}

            {/* Upload Controls */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                paddingTop: 16,
                borderTop: `1px solid ${c.slate100}`,
              }}
            >
              <span style={{ fontSize: 13, color: c.subtleText }}>
                {items.filter((i) => i.status === "done").length} of {items.length} uploaded
              </span>
              <div style={{ display: "flex", gap: 10 }}>
                {allDone && (
                  <button
                    className="btn-press"
                    onClick={onClose}
                    style={{
                      padding: "9px 20px",
                      borderRadius: 10,
                      border: `1px solid ${c.border}`,
                      background: c.white,
                      color: c.slate600,
                      fontSize: 13,
                      fontWeight: 600,
                      cursor: "pointer",
                      transition: "all 0.15s ease",
                    }}
                  >
                    Done
                  </button>
                )}
                {hasPending && (
                  <button
                    className="btn-press"
                    onClick={uploadAll}
                    style={{
                      padding: "9px 24px",
                      borderRadius: 10,
                      border: "none",
                      background: `linear-gradient(135deg, ${c.primary} 0%, ${tokens.primaryDark} 100%)`,
                      color: c.white,
                      fontSize: 13,
                      fontWeight: 600,
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      boxShadow: `0 4px 12px ${c.primary}30`,
                      transition: "all 0.15s ease",
                    }}
                  >
                    <Upload size={14} />
                    Upload {items.filter((i) => i.status === "pending").length} File
                    {items.filter((i) => i.status === "pending").length !== 1 ? "s" : ""}
                  </button>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── File Item Row ─────────────────────────────────────────────────────────────

interface FileItemRowProps {
  item: FileUploadItem;
  patients: any[];
  patientSearch: string;
  onPatientSearch: (s: string) => void;
  onUpdate: (id: string, patch: Partial<FileUploadItem>) => void;
  onRemove: (id: string) => void;
}

function FileItemRow({ item, patients, onUpdate, onRemove }: FileItemRowProps) {
  const [patientOpen, setPatientOpen] = useState(false);
  const [localSearch, setLocalSearch] = useState("");
  const patientRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (patientRef.current && !patientRef.current.contains(e.target as Node)) {
        setPatientOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const filteredPatients = useMemo(() => {
    const pts = patients as Array<{ pid?: number; fname?: string; lname?: string; name?: string }>;
    if (!localSearch) return pts.slice(0, 20);
    const q = localSearch.toLowerCase();
    return pts.filter((p) => {
      const name = `${p.fname ?? ""} ${p.lname ?? ""}`.toLowerCase();
      return name.includes(q) || String(p.pid ?? "").includes(q);
    }).slice(0, 20);
  }, [patients, localSearch]);

  const isFinished = item.status === "done" || item.status === "error";

  return (
    <div
      className={`animate-fade-in ${item.status === "error" ? "card-glow-rose" : "hover-lift"}`}
      style={{
        background: item.status === "error" ? c.red50 : c.white,
        border: `1px solid ${item.status === "error" ? tokens.dangerBorder : c.slate200}`,
        borderRadius: 10,
        padding: 16,
        transition: "all 0.2s ease",
      }}
    >
      <div style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
        {/* Thumbnail or icon */}
        <div
          style={{
            width: 52,
            height: 52,
            borderRadius: 8,
            background: c.white,
            border: `1px solid ${c.slate200}`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
            overflow: "hidden",
            position: "relative",
          }}
        >
          {item.previewUrl ? (
            <NextImage
              src={item.previewUrl}
              alt={item.file.name}
              fill
              style={{ objectFit: "cover" }}
            />
          ) : (
            fileIcon(item.file.type)
          )}
        </div>

        {/* Fields */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: 10,
            }}
          >
            <div>
              <p
                style={{
                  margin: 0,
                  fontSize: 13,
                  fontWeight: 600,
                  color: c.slate900,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  maxWidth: 320,
                }}
              >
                {item.file.name}
              </p>
              <p style={{ margin: 0, fontSize: 11, color: c.subtleText }}>
                {formatBytes(item.file.size)}
              </p>
            </div>
            {!isFinished && (
              <button
                onClick={() => onRemove(item.id)}
                style={{
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  color: c.slate400,
                  padding: 2,
                  borderRadius: 4,
                }}
                aria-label="Remove file"
              >
                <X size={15} />
              </button>
            )}
            {item.status === "done" && (
              <CheckCircle2 size={18} color={c.emerald500} />
            )}
            {item.status === "error" && (
              <AlertCircle size={18} color={c.red600} />
            )}
          </div>

          {!isFinished && (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 160px 140px",
                gap: 10,
                marginBottom: item.status === "uploading" ? 10 : 0,
              }}
            >
              {/* Patient picker */}
              <div ref={patientRef} style={{ position: "relative" }}>
                <button
                  onClick={() => setPatientOpen((v) => !v)}
                  style={{
                    width: "100%",
                    padding: "7px 10px",
                    borderRadius: 8,
                    border: `1px solid ${c.slate200}`,
                    background: c.white,
                    fontSize: 12,
                    color: item.patientName ? c.slate900 : c.slate400,
                    textAlign: "left",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                  }}
                >
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {item.patientName || "Select patient..."}
                  </span>
                  <ChevronDown size={12} color={c.slate400} />
                </button>
                {patientOpen && (
                  <div
                    style={{
                      position: "absolute",
                      top: "calc(100% + 4px)",
                      left: 0,
                      right: 0,
                      background: c.white,
                      border: `1px solid ${c.slate200}`,
                      borderRadius: 10,
                      boxShadow: "0 4px 20px rgba(0,0,0,0.10)",
                      zIndex: 200,
                      maxHeight: 220,
                      overflow: "hidden",
                      display: "flex",
                      flexDirection: "column",
                    }}
                  >
                    <div style={{ padding: "8px 10px", borderBottom: `1px solid ${c.slate100}` }}>
                      <input
                        autoFocus
                        placeholder="Search patient..."
                        value={localSearch}
                        onChange={(e) => setLocalSearch(e.target.value)}
                        style={{
                          width: "100%",
                          border: `1px solid ${c.slate200}`,
                          borderRadius: 6,
                          padding: "6px 8px",
                          fontSize: 12,
                          boxSizing: "border-box",
                        }}
                      />
                    </div>
                    <div style={{ overflowY: "auto", flex: 1 }}>
                      {filteredPatients.length === 0 && (
                        <div style={{ padding: "12px 12px", fontSize: 12, color: c.subtleText, textAlign: "center" }}>
                          No patients found
                        </div>
                      )}
                      {filteredPatients.map((p) => {
                        const pt = p as { pid?: number; fname?: string; lname?: string };
                        const name = `${pt.fname ?? ""} ${pt.lname ?? ""}`.trim();
                        return (
                          <button
                            key={pt.pid}
                            onClick={() => {
                              onUpdate(item.id, { patientId: String(pt.pid ?? ""), patientName: name });
                              setPatientOpen(false);
                              setLocalSearch("");
                            }}
                            style={{
                              display: "block",
                              width: "100%",
                              padding: "8px 12px",
                              textAlign: "left",
                              background: "none",
                              border: "none",
                              fontSize: 12,
                              color: c.slate900,
                              cursor: "pointer",
                              borderBottom: `1px solid ${c.slate50}`,
                            }}
                            onMouseEnter={(e) => ((e.currentTarget as HTMLButtonElement).style.background = c.slate50)}
                            onMouseLeave={(e) => ((e.currentTarget as HTMLButtonElement).style.background = "none")}
                          >
                            <span style={{ fontWeight: 600 }}>{name}</span>
                            <span style={{ color: c.subtleText, marginLeft: 6 }}>#{pt.pid}</span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>

              {/* Document type */}
              <select
                value={item.documentType}
                onChange={(e) => onUpdate(item.id, { documentType: e.target.value as DocumentType })}
                style={{
                  padding: "7px 10px",
                  borderRadius: 8,
                  border: `1px solid ${c.slate200}`,
                  background: c.white,
                  fontSize: 12,
                  color: c.slate900,
                  cursor: "pointer",
                }}
                aria-label="Document type"
              >
                {DOCUMENT_TYPES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>

              {/* Encounter date */}
              <input
                type="date"
                value={item.encounterDate}
                onChange={(e) => onUpdate(item.id, { encounterDate: e.target.value })}
                style={{
                  padding: "7px 10px",
                  borderRadius: 8,
                  border: `1px solid ${c.slate200}`,
                  background: c.white,
                  fontSize: 12,
                  color: c.slate900,
                }}
                aria-label="Encounter date"
              />
            </div>
          )}

          {item.status === "uploading" && (
            <ProgressBar value={item.progress} showPercent height={5} color={c.primary} />
          )}

          {item.status === "error" && (
            <p style={{ margin: 0, fontSize: 12, color: c.red600 }}>
              {item.error ?? "Upload failed"}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Status Badge ─────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: DocumentStatus }) {
  const cfg = statusConfig(status);
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        padding: "3px 10px",
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 600,
        background: cfg.bg,
        color: cfg.color,
        whiteSpace: "nowrap",
      }}
    >
      {cfg.pulse && (
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: 3,
            background: cfg.color,
            display: "inline-block",
            animation: "statusPulse 1.4s ease-in-out infinite",
          }}
        />
      )}
      {cfg.label}
    </span>
  );
}

// ─── Document Detail Modal ─────────────────────────────────────────────────────

interface DocumentDetailProps {
  doc: Document;
  onClose: () => void;
  onAnalyze: (id: string) => void;
  onConfirmDiagnosis: (docId: string, icd10: string, confirmed: boolean) => void;
}

function DocumentDetailModal({ doc, onClose, onAnalyze, onConfirmDiagnosis }: DocumentDetailProps) {
  const [activeTab, setActiveTab] = useState<AnalysisTab>("diagnoses");

  const tabs: { key: AnalysisTab; label: string; count?: number }[] = [
    { key: "diagnoses", label: "Diagnoses", count: doc.analysis_results?.diagnoses?.length },
    { key: "medications", label: "Medications", count: doc.analysis_results?.medications?.length },
    { key: "labs", label: "Labs", count: doc.analysis_results?.labs?.length },
    { key: "summary", label: "Clinical Summary" },
    { key: "meat", label: "MEAT Evidence" },
    { key: "raw", label: "Raw Text" },
  ];

  const hasResults = doc.status === "analyzed" || doc.status === "reviewed";

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 300,
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "flex-end",
        background: "rgba(15,23,42,0.45)",
        backdropFilter: "blur(3px)",
      }}
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Document detail"
    >
      <div
        className="animate-slide-up"
        style={{
          width: "min(800px, 95vw)",
          height: "100vh",
          background: c.white,
          display: "flex",
          flexDirection: "column",
          boxShadow: "-12px 0 60px rgba(0,0,0,0.15), -4px 0 20px rgba(0,0,0,0.08)",
          overflowY: "auto",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            padding: "20px 24px 16px",
            borderBottom: `1px solid ${c.slate200}`,
            position: "sticky",
            top: 0,
            background: c.white,
            zIndex: 10,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div
              style={{
                width: 40,
                height: 40,
                borderRadius: 10,
                background: c.slate100,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {fileIcon(doc.file_type)}
            </div>
            <div>
              <h2
                style={{
                  margin: 0,
                  fontSize: 16,
                  fontWeight: 700,
                  color: c.slate900,
                  maxWidth: 440,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {doc.filename}
              </h2>
              <p style={{ margin: "3px 0 0", fontSize: 12, color: c.subtleText }}>
                {doc.document_type} &middot; {doc.patient_name || "Unlinked"} &middot;{" "}
                {formatDate(doc.encounter_date)}
              </p>
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <StatusBadge status={doc.status} />
            <button
              onClick={onClose}
              style={{
                background: "none",
                border: "none",
                cursor: "pointer",
                color: c.slate400,
                padding: 4,
                borderRadius: 6,
                display: "flex",
              }}
              aria-label="Close detail panel"
            >
              <X size={20} />
            </button>
          </div>
        </div>

        <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
          {/* Top action row */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "12px 24px",
              borderBottom: `1px solid ${c.slate100}`,
            }}
          >
            {(doc.status === "uploaded" || doc.status === "error") && (
              <button
                className="btn-press"
                onClick={() => onAnalyze(doc.id)}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "8px 18px",
                  borderRadius: 8,
                  border: "none",
                  background: `linear-gradient(135deg, ${c.primary} 0%, ${tokens.accentPurple} 100%)`,
                  color: c.white,
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: "pointer",
                  boxShadow: `0 4px 14px ${c.primary}30`,
                  transition: "all 0.2s ease",
                }}
              >
                <Zap size={14} />
                Analyze Document
              </button>
            )}
            {!doc.patient_id && (
              <button
                className="btn-press"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "8px 16px",
                  borderRadius: 8,
                  border: `1.5px solid ${c.slate200}`,
                  background: c.white,
                  color: c.slate700,
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: "pointer",
                  transition: "all 0.15s ease",
                }}
              >
                <Link2 size={13} />
                Link to Patient
              </button>
            )}
          </div>

          <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
            {/* Main content */}
            <div style={{ flex: 1, overflow: "auto", padding: "0 0 24px" }}>
              {!hasResults && (
                <div style={{ padding: "40px 24px" }}>
                  <EmptyState
                    icon={<Zap size={28} color={c.slate400} />}
                    title={
                      doc.status === "processing"
                        ? "Analysis in progress..."
                        : "Document not yet analyzed"
                    }
                    description={
                      doc.status === "processing"
                        ? "AI is extracting clinical information. This typically takes 10-30 seconds."
                        : "Click 'Analyze Document' to extract diagnoses, medications, and lab results."
                    }
                  />
                </div>
              )}

              {hasResults && (
                <>
                  {/* Tabs */}
                  <div
                    style={{
                      display: "flex",
                      borderBottom: `1px solid ${c.slate200}`,
                      padding: "0 24px",
                      overflowX: "auto",
                    }}
                  >
                    {tabs.map((tab) => (
                      <button
                        key={tab.key}
                        onClick={() => setActiveTab(tab.key)}
                        style={{
                          padding: "12px 14px",
                          background: "none",
                          border: "none",
                          borderBottom: activeTab === tab.key ? `2px solid ${c.primary}` : "2px solid transparent",
                          fontSize: 13,
                          fontWeight: activeTab === tab.key ? 600 : 500,
                          color: activeTab === tab.key ? c.primary : c.slate600,
                          cursor: "pointer",
                          display: "flex",
                          alignItems: "center",
                          gap: 6,
                          whiteSpace: "nowrap",
                          marginBottom: -1,
                        }}
                      >
                        {tab.label}
                        {tab.count !== undefined && tab.count > 0 && (
                          <span
                            style={{
                              fontSize: 11,
                              fontWeight: 600,
                              background: activeTab === tab.key ? `${c.primary}1A` : c.slate100,
                              color: activeTab === tab.key ? c.primary : c.slate600,
                              padding: "1px 6px",
                              borderRadius: 999,
                            }}
                          >
                            {tab.count}
                          </span>
                        )}
                      </button>
                    ))}
                  </div>

                  <div style={{ padding: "20px 24px" }}>
                    {/* Diagnoses Tab */}
                    {activeTab === "diagnoses" && (
                      <DiagnosesTab
                        diagnoses={doc.analysis_results?.diagnoses ?? []}
                        docId={doc.id}
                        onConfirm={onConfirmDiagnosis}
                      />
                    )}

                    {/* Medications Tab */}
                    {activeTab === "medications" && (
                      <MedicationsTab medications={doc.analysis_results?.medications ?? []} />
                    )}

                    {/* Labs Tab */}
                    {activeTab === "labs" && (
                      <LabsTab labs={doc.analysis_results?.labs ?? []} />
                    )}

                    {/* Clinical Summary Tab */}
                    {activeTab === "summary" && (
                      <div>
                        {doc.analysis_results?.clinical_summary ? (
                          <div
                            className="animate-fade-in premium-card"
                            style={{
                              padding: 20,
                              fontSize: 14,
                              lineHeight: 1.75,
                              color: c.slate700,
                              whiteSpace: "pre-wrap",
                            }}
                          >
                            {doc.analysis_results.clinical_summary}
                          </div>
                        ) : (
                          <EmptyState title="No clinical summary available" />
                        )}
                      </div>
                    )}

                    {/* MEAT Evidence Tab */}
                    {activeTab === "meat" && (
                      <MeatTab meat={doc.analysis_results?.meat_evidence ?? null} />
                    )}

                    {/* Raw Text Tab */}
                    {activeTab === "raw" && (
                      <div>
                        {doc.extracted_text || doc.analysis_results?.raw_text ? (
                          <pre
                            style={{
                              background: c.slate900,
                              color: tokens.slate200,
                              borderRadius: 10,
                              padding: 20,
                              fontSize: 12,
                              lineHeight: 1.6,
                              overflowX: "auto",
                              whiteSpace: "pre-wrap",
                              wordBreak: "break-word",
                              maxHeight: 520,
                              overflowY: "auto",
                            }}
                          >
                            {doc.extracted_text ?? doc.analysis_results?.raw_text}
                          </pre>
                        ) : (
                          <EmptyState title="No extracted text available" />
                        )}
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>

            {/* Sidebar metadata */}
            <div
              style={{
                width: 220,
                flexShrink: 0,
                borderLeft: `1px solid ${c.slate200}`,
                padding: "20px 16px",
                background: c.slate50,
              }}
            >
              <p
                style={{
                  margin: "0 0 12px",
                  fontSize: 11,
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                  color: c.slate400,
                }}
              >
                Document Info
              </p>
              <DataRow label="Type" value={doc.file_type?.toUpperCase() || "—"} />
              <DataRow label="Size" value={doc.file_size ? formatBytes(doc.file_size) : "—"} />
              {doc.page_count != null && <DataRow label="Pages" value={doc.page_count} />}
              <DataRow label="Uploaded" value={formatDate(doc.upload_date)} />
              {doc.processing_time_ms != null && (
                <DataRow
                  label="Processing"
                  value={
                    doc.processing_time_ms > 1000
                      ? `${(doc.processing_time_ms / 1000).toFixed(1)}s`
                      : `${doc.processing_time_ms}ms`
                  }
                />
              )}
              {doc.tokens_used != null && (
                <DataRow label="Tokens" value={doc.tokens_used.toLocaleString()} />
              )}
              {doc.hcc_count > 0 && (
                <DataRow
                  label="HCCs Found"
                  value={
                    <span
                      style={{
                        background: `${c.emerald500}1A`,
                        color: c.emerald600,
                        padding: "2px 8px",
                        borderRadius: 999,
                        fontSize: 12,
                        fontWeight: 700,
                      }}
                    >
                      {doc.hcc_count}
                    </span>
                  }
                />
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Analysis Sub-tabs ─────────────────────────────────────────────────────────

function DiagnosesTab({
  diagnoses,
  docId,
  onConfirm,
}: {
  diagnoses: DiagnosisResult[];
  docId: string;
  onConfirm: (docId: string, icd10: string, confirmed: boolean) => void;
}) {
  if (!diagnoses.length) return <EmptyState title="No diagnoses extracted" />;
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr style={{ background: c.slate50 }}>
            {["ICD-10", "Description", "HCC", "Confidence", "Page", "Evidence", "Action"].map(
              (h) => (
                <th
                  key={h}
                  style={{
                    padding: "8px 12px",
                    textAlign: "left",
                    fontSize: 11,
                    fontWeight: 700,
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                    color: c.slate400,
                    borderBottom: `1px solid ${c.slate200}`,
                    whiteSpace: "nowrap",
                  }}
                >
                  {h}
                </th>
              )
            )}
          </tr>
        </thead>
        <tbody>
          {diagnoses.map((d, i) => (
            <tr
              key={d.icd10_code || i}
              style={{
                borderBottom: `1px solid ${c.slate100}`,
                background:
                  d.confirmed === true
                    ? c.emerald50
                    : d.confirmed === false
                    ? c.red50
                    : "transparent",
              }}
            >
              <td style={{ padding: "10px 12px", fontFamily: "monospace", fontWeight: 700, color: c.primary, whiteSpace: "nowrap" }}>
                {d.icd10_code}
              </td>
              <td style={{ padding: "10px 12px", color: c.slate900, maxWidth: 200 }}>
                {d.description}
              </td>
              <td style={{ padding: "10px 12px", whiteSpace: "nowrap" }}>
                {d.hcc_number ? (
                  <span
                    style={{
                      background: `${c.violet500}1A`,
                      color: c.violet500,
                      padding: "2px 8px",
                      borderRadius: 6,
                      fontSize: 11,
                      fontWeight: 700,
                    }}
                  >
                    HCC {d.hcc_number}
                  </span>
                ) : (
                  <span style={{ color: c.slate400 }}>—</span>
                )}
              </td>
              <td style={{ padding: "10px 12px" }}>
                <ConfidencePill value={d.confidence} />
              </td>
              <td style={{ padding: "10px 12px", color: c.subtleText, textAlign: "center" }}>
                {d.page_number ?? "—"}
              </td>
              <td
                style={{
                  padding: "10px 12px",
                  fontSize: 12,
                  color: c.subtleText,
                  maxWidth: 200,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
                title={d.evidence_text}
              >
                {d.evidence_text || "—"}
              </td>
              <td style={{ padding: "10px 12px", whiteSpace: "nowrap" }}>
                {d.confirmed === null || d.confirmed === undefined ? (
                  <div style={{ display: "flex", gap: 6 }}>
                    <button
                      className="btn-press"
                      onClick={() => onConfirm(docId, d.icd10_code, true)}
                      style={{
                        padding: "4px 10px",
                        borderRadius: 6,
                        border: `1.5px solid ${c.emerald500}`,
                        background: `${c.emerald500}08`,
                        color: c.emerald500,
                        fontSize: 11,
                        fontWeight: 600,
                        cursor: "pointer",
                        transition: "all 0.15s ease",
                      }}
                    >
                      Confirm
                    </button>
                    <button
                      className="btn-press"
                      onClick={() => onConfirm(docId, d.icd10_code, false)}
                      style={{
                        padding: "4px 10px",
                        borderRadius: 6,
                        border: `1.5px solid ${c.red600}`,
                        background: `${c.red600}08`,
                        color: c.red600,
                        fontSize: 11,
                        fontWeight: 600,
                        cursor: "pointer",
                        transition: "all 0.15s ease",
                      }}
                    >
                      Reject
                    </button>
                  </div>
                ) : (
                  <span
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      color: d.confirmed ? c.emerald600 : c.red600,
                    }}
                  >
                    {d.confirmed ? "Confirmed" : "Rejected"}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MedicationsTab({ medications }: { medications: MedicationResult[] }) {
  if (!medications.length) return <EmptyState title="No medications extracted" />;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {medications.map((m, i) => (
        <div
          key={m.name || i}
          className={`animate-fade-in hover-lift stagger-${Math.min(i + 1, 6)}`}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 16,
            padding: "14px 18px",
            background: c.white,
            border: `1px solid ${c.slate200}`,
            borderRadius: 10,
            transition: "all 0.2s ease",
          }}
        >
          <div
            style={{
              width: 8,
              height: 8,
              borderRadius: 4,
              background: c.blue500,
              flexShrink: 0,
            }}
          />
          <span style={{ fontSize: 14, fontWeight: 600, color: c.slate900, flex: 1 }}>
            {m.name}
          </span>
          {m.dose && (
            <span style={{ fontSize: 12, color: c.subtleText }}>
              {m.dose}
            </span>
          )}
          {m.frequency && (
            <span
              style={{
                fontSize: 11,
                background: `${c.blue500}1A`,
                color: c.blue500,
                padding: "2px 8px",
                borderRadius: 999,
                fontWeight: 600,
              }}
            >
              {m.frequency}
            </span>
          )}
          {m.route && (
            <span style={{ fontSize: 12, color: c.subtleText }}>{m.route}</span>
          )}
        </div>
      ))}
    </div>
  );
}

function LabsTab({ labs }: { labs: LabResult[] }) {
  if (!labs.length) return <EmptyState title="No lab values extracted" />;
  const flagColor = (flag?: string) => {
    if (flag === "high") return c.red600;
    if (flag === "low") return c.blue500;
    return c.emerald500;
  };
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr style={{ background: c.slate50 }}>
            {["Test", "Value", "Reference Range", "Status"].map((h) => (
              <th
                key={h}
                style={{
                  padding: "8px 12px",
                  textAlign: "left",
                  fontSize: 11,
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                  color: c.slate400,
                  borderBottom: `1px solid ${c.slate200}`,
                }}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {labs.map((lab, i) => (
            <tr key={lab.name || i} style={{ borderBottom: `1px solid ${c.slate100}` }}>
              <td style={{ padding: "10px 12px", fontWeight: 600, color: c.slate900 }}>
                {lab.name}
              </td>
              <td style={{ padding: "10px 12px", fontFamily: "monospace", fontWeight: 700, color: flagColor(lab.flag) }}>
                {lab.value} {lab.unit && <span style={{ fontWeight: 400, color: c.subtleText }}>{lab.unit}</span>}
              </td>
              <td style={{ padding: "10px 12px", color: c.subtleText }}>
                {lab.reference_range ?? "—"}
              </td>
              <td style={{ padding: "10px 12px" }}>
                {lab.flag ? (
                  <span
                    style={{
                      fontSize: 11,
                      fontWeight: 700,
                      textTransform: "uppercase",
                      color: flagColor(lab.flag),
                      background: `${flagColor(lab.flag)}1A`,
                      padding: "2px 8px",
                      borderRadius: 999,
                    }}
                  >
                    {lab.flag}
                  </span>
                ) : (
                  <span
                    style={{
                      fontSize: 11,
                      fontWeight: 700,
                      color: c.emerald500,
                      background: `${c.emerald500}1A`,
                      padding: "2px 8px",
                      borderRadius: 999,
                    }}
                  >
                    Normal
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MeatTab({ meat }: { meat: MeatEvidence | null }) {
  if (!meat) return <EmptyState title="No MEAT evidence extracted" />;
  const sections = [
    { key: "M" as const, label: "Monitored", color: c.primary, desc: "Condition being monitored with tests, medications, or other management." },
    { key: "E" as const, label: "Evaluated", color: c.violet500, desc: "Condition assessed, reviewed, or addressed at the visit." },
    { key: "A" as const, label: "Assessed", color: c.amber500, desc: "Status of condition noted or clinical judgment applied." },
    { key: "T" as const, label: "Treated", color: c.emerald500, desc: "Active treatment, therapy, or intervention documented." },
  ];
  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <MeatIndicator meat={meat} />
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {sections.map((s, idx) => (
          <div
            key={s.key}
            className={`animate-fade-in hover-lift stagger-${idx + 1}`}
            style={{
              border: `1px solid ${meat[s.key] ? s.color + "40" : c.slate200}`,
              borderRadius: 10,
              padding: 16,
              background: meat[s.key] ? `${s.color}08` : c.white,
              transition: "all 0.2s ease",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: meat[s.key] ? 8 : 0 }}>
              <span
                style={{
                  width: 28,
                  height: 28,
                  borderRadius: 6,
                  background: meat[s.key] ? `${s.color}1A` : c.slate100,
                  color: meat[s.key] ? s.color : c.slate400,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 13,
                  fontWeight: 800,
                }}
              >
                {s.key}
              </span>
              <span style={{ fontSize: 14, fontWeight: 700, color: meat[s.key] ? s.color : c.slate400 }}>
                {s.label}
              </span>
              {!meat[s.key] && (
                <span style={{ fontSize: 12, color: c.slate400, marginLeft: 4 }}>Not documented</span>
              )}
            </div>
            {meat[s.key] && (
              <p style={{ margin: 0, fontSize: 13, color: c.slate700, lineHeight: 1.6, paddingLeft: 36 }}>
                {meat[s.key]}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function DocumentsPage() {
  const queryClient = useQueryClient();

  // Filters
  const [statusFilter, setStatusFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [patientFilter, setPatientFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);

  // UI state
  const [showUpload, setShowUpload] = useState(false);
  const [selectedDoc, setSelectedDoc] = useState<Document | null>(null);
  const [docTab, setDocTab] = useState<"raf" | "openemr">("raf");
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const queryParams = { status: statusFilter, document_type: typeFilter, patient_id: patientFilter, date_from: dateFrom, date_to: dateTo, page };

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["documents", queryParams],
    queryFn: () => fetchDocuments(queryParams),
    refetchInterval: 15000,
  });

  const total = data?.total ?? 0;
  const allDocs = data?.documents ?? [];
  const stats = {
    total,
    analyzed: allDocs.filter((d) => d.status === "analyzed" || d.status === "reviewed").length,
    hcc_count: allDocs.reduce((sum, d) => sum + (d.hcc_count || 0), 0),
    pending: allDocs.filter((d) => d.status === "uploaded" || d.status === "processing").length,
  };
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  // Filter documents by local search
  const filteredDocs = useMemo(() => {
    const documents = data?.documents ?? [];
    if (!search) return documents;
    const q = search.toLowerCase();
    return documents.filter(
      (d) =>
        d.filename.toLowerCase().includes(q) ||
        d.patient_name?.toLowerCase().includes(q) ||
        d.document_type.toLowerCase().includes(q)
    );
  }, [data, search]);

  const analyzeMutation = useMutation({
    mutationFn: analyzeDocument,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["documents"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteDocument,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["documents"] }),
  });

  const confirmMutation = useMutation({
    mutationFn: ({ docId, icd10, confirmed }: { docId: string; icd10: string; confirmed: boolean }) =>
      confirmDiagnosis(docId, icd10, confirmed),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["documents"] }),
  });

  const handleAnalyze = useCallback(
    (id: string) => {
      analyzeMutation.mutate(id);
      if (selectedDoc?.id === id) {
        setSelectedDoc((prev) => prev ? { ...prev, status: "processing" } : prev);
      }
    },
    [analyzeMutation, selectedDoc]
  );

  const handleDelete = useCallback(
    (id: string) => {
      setConfirmDelete(id);
    },
    []
  );

  const handleConfirmDeleteAction = useCallback(() => {
    if (confirmDelete) {
      deleteMutation.mutate(confirmDelete);
      if (selectedDoc?.id === confirmDelete) setSelectedDoc(null);
      setConfirmDelete(null);
    }
  }, [confirmDelete, deleteMutation, selectedDoc]);

  const handleConfirmDiagnosis = useCallback(
    (docId: string, icd10: string, confirmed: boolean) => {
      confirmMutation.mutate({ docId, icd10, confirmed });
    },
    [confirmMutation]
  );

  const clearFilters = () => {
    setStatusFilter("");
    setTypeFilter("");
    setPatientFilter("");
    setDateFrom("");
    setDateTo("");
    setSearch("");
    setPage(0);
  };

  const hasFilters = statusFilter || typeFilter || patientFilter || dateFrom || dateTo || search;

  return (
    <div className="rci-page-pad-desktop" style={{ padding: "20px 16px", maxWidth: 1280, margin: "0 auto" }}>
      <PageHeader
        title="Clinical Documents"
        subtitle="Upload, analyze, and manage clinical documents for HCC extraction"
        icon={<FileImage size={24} color={c.primary} />}
        actions={
          <button
            className="btn-press"
            onClick={() => setShowUpload((v) => !v)}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              padding: "10px 22px",
              borderRadius: 10,
              border: "none",
              background: `linear-gradient(135deg, ${c.primary} 0%, ${tokens.primaryDark} 100%)`,
              color: c.white,
              fontSize: 14,
              fontWeight: 600,
              cursor: "pointer",
              transition: "all 0.2s ease",
              boxShadow: `0 4px 14px ${c.primary}30`,
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLButtonElement).style.boxShadow = `0 6px 20px ${c.primary}40`;
              (e.currentTarget as HTMLButtonElement).style.transform = "translateY(-1px)";
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.boxShadow = `0 4px 14px ${c.primary}30`;
              (e.currentTarget as HTMLButtonElement).style.transform = "translateY(0)";
            }}
          >
            <Upload size={15} />
            Upload Documents
          </button>
        }
      />

      {/* Tab Switcher */}
      <div style={{ display: "flex", gap: 0, marginBottom: 24, borderBottom: `2px solid ${c.slate200}` }}>
        {([
          { key: "raf" as const, label: "RAF Documents", icon: <FileText size={15} /> },
          { key: "openemr" as const, label: "OpenEMR Documents", icon: <Database size={15} /> },
        ]).map((tab) => (
          <button
            key={tab.key}
            onClick={() => setDocTab(tab.key)}
            style={{
              display: "inline-flex", alignItems: "center", gap: 8,
              padding: "12px 24px", border: "none", background: "transparent",
              fontSize: 14, fontWeight: docTab === tab.key ? 700 : 500,
              color: docTab === tab.key ? c.primary : c.slate600,
              borderBottom: docTab === tab.key ? `2px solid ${c.primary}` : "2px solid transparent",
              marginBottom: -2, cursor: "pointer", transition: "all 0.2s ease",
            }}
          >
            {tab.icon} {tab.label}
          </button>
        ))}
      </div>

      {docTab === "openemr" ? (
        <OpenEMRDocumentsPanel />
      ) : (
      <>
      {/* Stats Row */}
      <div
        id="docs-kpi-grid"
        role="status"
        aria-live="polite"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 16,
          marginBottom: 24,
        }}
      >
        <div className="animate-fade-in stagger-1">
          <MetricCard
            label="Total Documents"
            value={isLoading ? "—" : stats.total.toLocaleString()}
            icon={<FileImage size={18} />}
            loading={isLoading}
          />
        </div>
        <div className="animate-fade-in stagger-2">
          <MetricCard
            label="Documents Analyzed"
            value={isLoading ? "—" : stats.analyzed.toLocaleString()}
            icon={<CheckCircle2 size={18} />}
            intent="success"
            loading={isLoading}
          />
        </div>
        <div className="animate-fade-in stagger-3">
          <MetricCard
            label="HCC Codes Found"
            value={isLoading ? "—" : stats.hcc_count.toLocaleString()}
            icon={<Zap size={18} />}
            loading={isLoading}
          />
        </div>
        <div className="animate-fade-in stagger-4">
          <MetricCard
            label="Pending Review"
            value={isLoading ? "—" : stats.pending.toLocaleString()}
            icon={<Clock size={18} />}
            intent="warning"
            loading={isLoading}
          />
        </div>
      </div>

      {/* Upload Panel */}
      {showUpload && (
        <UploadPanel
          onClose={() => setShowUpload(false)}
          onUploaded={() => {
            queryClient.invalidateQueries({ queryKey: ["documents"] });
          }}
        />
      )}

      {/* Filters */}
      <div
        className="premium-card animate-fade-in stagger-5"
        style={{
          padding: "14px 20px",
          marginBottom: 16,
          display: "flex",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        {/* Search */}
        <div style={{ position: "relative", flex: "1 1 220px" }}>
          <Search
            size={14}
            style={{
              position: "absolute",
              left: 10,
              top: "50%",
              transform: "translateY(-50%)",
              color: c.slate400,
              pointerEvents: "none",
            }}
          />
          <input
            type="text"
            placeholder="Search documents..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search documents"
            style={{
              width: "100%",
              paddingLeft: 32,
              paddingRight: 12,
              paddingTop: 7,
              paddingBottom: 7,
              borderRadius: 8,
              border: `1px solid ${c.slate200}`,
              fontSize: 13,
              color: c.slate900,
              boxSizing: "border-box",
            }}
          />
        </div>

        {/* Status filter */}
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(0); }}
          aria-label="Filter by status"
          style={{
            padding: "7px 10px",
            borderRadius: 8,
            border: `1px solid ${c.slate200}`,
            fontSize: 13,
            color: statusFilter ? c.slate900 : c.slate400,
            background: c.white,
            cursor: "pointer",
          }}
        >
          <option value="">All Statuses</option>
          <option value="uploaded">Uploaded</option>
          <option value="processing">Processing</option>
          <option value="analyzed">Analyzed</option>
          <option value="reviewed">Reviewed</option>
          <option value="error">Error</option>
        </select>

        {/* Document type filter */}
        <select
          value={typeFilter}
          onChange={(e) => { setTypeFilter(e.target.value); setPage(0); }}
          aria-label="Filter by document type"
          style={{
            padding: "7px 10px",
            borderRadius: 8,
            border: `1px solid ${c.slate200}`,
            fontSize: 13,
            color: typeFilter ? c.slate900 : c.slate400,
            background: c.white,
            cursor: "pointer",
          }}
        >
          <option value="">All Types</option>
          {DOCUMENT_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>

        {/* Date range */}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => { setDateFrom(e.target.value); setPage(0); }}
            aria-label="From date"
            style={{
              padding: "7px 10px",
              borderRadius: 8,
              border: `1px solid ${c.slate200}`,
              fontSize: 13,
              color: c.slate900,
            }}
          />
          <span style={{ fontSize: 12, color: c.slate400 }}>to</span>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => { setDateTo(e.target.value); setPage(0); }}
            aria-label="To date"
            style={{
              padding: "7px 10px",
              borderRadius: 8,
              border: `1px solid ${c.slate200}`,
              fontSize: 13,
              color: c.slate900,
            }}
          />
        </div>

        {hasFilters && (
          <button
            onClick={clearFilters}
            style={{
              background: "none",
              border: "none",
              fontSize: 13,
              color: c.slate400,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: 4,
              padding: "4px 6px",
              borderRadius: 6,
            }}
          >
            <X size={13} /> Clear
          </button>
        )}

        <span style={{ marginLeft: "auto", fontSize: 12, color: c.subtleText, whiteSpace: "nowrap" }}>
          {total.toLocaleString()} document{total !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Documents Table */}
      <div
        className="premium-card animate-fade-in stagger-6"
        aria-live="polite"
        style={{
          overflow: "hidden",
        }}
      >
        {/* Table Header */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(200px, 2fr) 150px 160px 120px 100px 80px 100px",
            padding: "10px 16px",
            background: c.slate50,
            borderBottom: `1px solid ${c.slate200}`,
            gap: 8,
          }}
        >
          {[
            "Document Name",
            "Type",
            "Patient",
            "Date",
            "Status",
            "HCCs",
            "Actions",
          ].map((h) => (
            <span
              key={h}
              style={{
                fontSize: 11,
                fontWeight: 700,
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                color: c.slate400,
              }}
            >
              {h}
            </span>
          ))}
        </div>

        {/* Loading skeletons */}
        {isLoading &&
          Array.from({ length: 8 }).map((_, i) => (
            <div
              key={i}
              style={{
                display: "grid",
                gridTemplateColumns: "minmax(200px, 2fr) 150px 160px 120px 100px 80px 100px",
                padding: "0 16px",
                height: 56,
                borderBottom: `1px solid ${c.slate100}`,
                alignItems: "center",
                gap: 8,
              }}
            >
              {[2, 1, 1.2, 0.8, 0.7, 0.5, 0.8].map((w, j) => (
                <div
                  key={j}
                  className="shimmer"
                  style={{
                    height: 12,
                    borderRadius: 6,
                    background: c.slate100,
                    width: `${w * 60}%`,
                  }}
                />
              ))}
            </div>
          ))}

        {/* Error state */}
        {isError && (
          <div style={{ padding: "40px 24px", textAlign: "center" }}>
            <AlertCircle size={32} color={c.red600} style={{ marginBottom: 12 }} />
            <p style={{ fontSize: 14, color: c.slate700, marginBottom: 12 }}>Failed to load documents</p>
            <button
              className="btn-press"
              onClick={() => refetch()}
              style={{
                padding: "8px 20px",
                borderRadius: 8,
                border: `1px solid ${c.slate200}`,
                background: c.white,
                color: c.slate700,
                fontSize: 13,
                fontWeight: 600,
                cursor: "pointer",
                transition: "all 0.15s ease",
              }}
            >
              Retry
            </button>
          </div>
        )}

        {/* Empty state */}
        {!isLoading && !isError && filteredDocs.length === 0 && (
          <EmptyState
            icon={<FileImage size={32} color={c.slate400} />}
            title={hasFilters ? "No documents match your filters" : "No documents uploaded yet"}
            description={
              hasFilters
                ? "Try adjusting or clearing your filters."
                : "Upload clinical documents to extract HCC diagnoses with AI analysis."
            }
          />
        )}

        {/* Document rows */}
        {!isLoading &&
          !isError &&
          filteredDocs.map((doc) => (
            <DocumentRow
              key={doc.id}
              doc={doc}
              onView={() => setSelectedDoc(doc)}
              onAnalyze={handleAnalyze}
              onDelete={handleDelete}
            />
          ))}

        {/* Pagination */}
        {!isLoading && totalPages > 1 && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 16,
              padding: "14px 20px",
              borderTop: `1px solid ${c.slate200}`,
              background: c.slate50,
            }}
          >
            <button
              className={page === 0 ? "" : "btn-press"}
              disabled={page === 0}
              onClick={() => setPage((p) => p - 1)}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                padding: "6px 14px",
                borderRadius: 8,
                border: `1px solid ${c.slate200}`,
                background: c.white,
                fontSize: 13,
                fontWeight: 600,
                color: page === 0 ? c.slate200 : c.slate600,
                cursor: page === 0 ? "not-allowed" : "pointer",
                opacity: page === 0 ? 0.5 : 1,
                transition: "all 0.15s ease",
              }}
              aria-label="Previous page"
            >
              <ChevronLeft size={14} /> Previous
            </button>
            <span style={{ fontSize: 13, color: c.subtleText }}>
              Page <strong style={{ color: c.slate900 }}>{page + 1}</strong> of{" "}
              <strong style={{ color: c.slate900 }}>{totalPages}</strong>
            </span>
            <button
              className={page >= totalPages - 1 ? "" : "btn-press"}
              disabled={page >= totalPages - 1}
              onClick={() => setPage((p) => p + 1)}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                padding: "6px 14px",
                borderRadius: 8,
                border: `1px solid ${c.slate200}`,
                background: c.white,
                fontSize: 13,
                fontWeight: 600,
                color: page >= totalPages - 1 ? c.slate200 : c.slate600,
                cursor: page >= totalPages - 1 ? "not-allowed" : "pointer",
                opacity: page >= totalPages - 1 ? 0.5 : 1,
                transition: "all 0.15s ease",
              }}
              aria-label="Next page"
            >
              Next <ChevronRight size={14} />
            </button>
          </div>
        )}
      </div>

      {/* Document Detail Modal */}
      {selectedDoc && (
        <DocumentDetailModal
          doc={selectedDoc}
          onClose={() => setSelectedDoc(null)}
          onAnalyze={handleAnalyze}
          onConfirmDiagnosis={handleConfirmDiagnosis}
        />
      )}
      </>
      )}

      {/* Delete Confirmation Modal */}
      {confirmDelete && (
        <div style={{
          position: "fixed", inset: 0, zIndex: 9999,
          display: "flex", alignItems: "center", justifyContent: "center",
          background: "rgba(0,0,0,0.4)", backdropFilter: "blur(4px)",
        }}>
          <div style={{
            background: tokens.white, borderRadius: 10, padding: "28px 32px",
            maxWidth: 400, width: "90%", boxShadow: "0 20px 60px rgba(0,0,0,0.15)",
          }}>
            <h3 style={{ margin: "0 0 8px", fontSize: 16, fontWeight: 700, color: tokens.slate900 }}>
              Delete Document
            </h3>
            <p style={{ margin: "0 0 24px", fontSize: 14, color: tokens.slate500, lineHeight: 1.5 }}>
              Are you sure you want to delete this document? This action cannot be undone.
            </p>
            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button
                onClick={() => setConfirmDelete(null)}
                style={{
                  padding: "8px 18px", borderRadius: 8, border: `1px solid ${tokens.slate200}`,
                  background: tokens.white, color: tokens.slate700, fontSize: 13, fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmDeleteAction}
                style={{
                  padding: "8px 18px", borderRadius: 8, border: "none",
                  background: tokens.riskHigh, color: tokens.white, fontSize: 13, fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}

      <style>{`
        @keyframes statusPulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
        @keyframes docPulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.45; }
        }
        @media (max-width: 640px) {
          #docs-kpi-grid { grid-template-columns: repeat(2, 1fr) !important; }
        }
      `}</style>
    </div>
  );
}

// ─── OpenEMR Documents Panel ─────────────────────────────────────────────────

interface OpenEMRDocument {
  openemr_doc_id: number;
  name: string;
  mimetype: string;
  size: number;
  date: string;
  patient_id: number;
  patient_name: string;
  category: string;
  already_imported: boolean;
}

function OpenEMRDocumentsPanel() {
  const queryClient = useQueryClient();
  const [patientIdFilter, setPatientIdFilter] = useState("");
  const [pullingIds, setPullingIds] = useState<Set<number>>(new Set());
  const [pullingAll, setPullingAll] = useState(false);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["openemr-documents", patientIdFilter],
    queryFn: async () => {
      const params = patientIdFilter ? { patient_id: patientIdFilter } : {};
      const res = await api.get("/api/documents/openemr/list", { params });
      return res.data as { total: number; documents: OpenEMRDocument[] };
    },
    retry: 1,
  });

  const documents = data?.documents ?? [];
  const totalCount = data?.total ?? 0;
  const importedCount = documents.filter((d) => d.already_imported).length;
  const unimportedCount = documents.filter((d) => !d.already_imported).length;

  const pullMutation = useMutation({
    mutationFn: async (docId: number) => {
      const res = await api.post(`/api/documents/openemr/pull/${docId}?auto_analyze=true&auto_approve=false`);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["openemr-documents"] });
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });

  const handlePull = async (docId: number) => {
    setPullingIds((prev) => new Set(prev).add(docId));
    try {
      await pullMutation.mutateAsync(docId);
    } finally {
      setPullingIds((prev) => {
        const next = new Set(prev);
        next.delete(docId);
        return next;
      });
    }
  };

  const handlePullAll = async () => {
    const unimported = documents.filter((d) => !d.already_imported);
    if (unimported.length === 0) return;
    if (!confirm(`Pull and analyze ${unimported.length} unimported document(s)?`)) return;
    setPullingAll(true);
    try {
      for (const doc of unimported) {
        setPullingIds((prev) => new Set(prev).add(doc.openemr_doc_id));
        try {
          await pullMutation.mutateAsync(doc.openemr_doc_id);
        } catch {
          // continue with remaining
        } finally {
          setPullingIds((prev) => {
            const next = new Set(prev);
            next.delete(doc.openemr_doc_id);
            return next;
          });
        }
      }
    } finally {
      setPullingAll(false);
    }
  };

  return (
    <ErrorBoundary fallbackTitle="Documents page failed to load">
    <div>
      {/* Stats */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 24 }}>
        <MetricCard label="Total OpenEMR Docs" value={isLoading ? "—" : totalCount.toLocaleString("en-US")} icon={<Database size={18} />} loading={isLoading} />
        <MetricCard label="Already Imported" value={isLoading ? "—" : importedCount.toLocaleString("en-US")} icon={<CheckCircle2 size={18} />} intent="success" loading={isLoading} />
        <MetricCard label="Pending Import" value={isLoading ? "—" : unimportedCount.toLocaleString("en-US")} icon={<Clock size={18} />} intent="warning" loading={isLoading} />
      </div>

      {/* Filter bar */}
      <div style={{
        display: "flex", alignItems: "center", gap: 12, marginBottom: 20,
        padding: "12px 16px", borderRadius: 10, background: c.white,
        border: `1px solid ${c.border}`,
      }}>
        <Search size={16} color={c.slate400} />
        <input
          placeholder="Filter by Patient ID..."
          value={patientIdFilter}
          onChange={(e) => setPatientIdFilter(e.target.value)}
          style={{
            flex: 1, border: "none", fontSize: 14,
            color: c.slate900, background: "transparent",
          }}
        />
        {patientIdFilter && (
          <button onClick={() => setPatientIdFilter("")} style={{ border: "none", background: "transparent", cursor: "pointer", color: c.slate400 }}>
            <X size={16} />
          </button>
        )}
        <button
          onClick={() => refetch()}
          style={{
            display: "inline-flex", alignItems: "center", gap: 6,
            padding: "8px 16px", borderRadius: 8, border: `1px solid ${c.border}`,
            background: c.white, fontSize: 13, fontWeight: 500, color: c.slate700,
            cursor: "pointer",
          }}
        >
          <RefreshCw size={14} /> Refresh
        </button>
        <button
          onClick={handlePullAll}
          disabled={pullingAll || unimportedCount === 0}
          style={{
            display: "inline-flex", alignItems: "center", gap: 6,
            padding: "8px 16px", borderRadius: 8, border: "none",
            background: unimportedCount === 0 ? c.slate200 : `linear-gradient(135deg, ${c.primary} 0%, ${tokens.primaryDark} 100%)`,
            fontSize: 13, fontWeight: 600, color: unimportedCount === 0 ? c.slate400 : c.white,
            cursor: unimportedCount === 0 ? "default" : "pointer",
            opacity: pullingAll ? 0.7 : 1,
          }}
        >
          <Download size={14} /> {pullingAll ? "Pulling..." : `Pull All Unimported (${unimportedCount})`}
        </button>
      </div>

      {/* Table */}
      <div style={{
        borderRadius: 14, border: `1px solid ${c.border}`, background: c.white, overflow: "hidden",
      }}>
        {/* Header */}
        <div style={{
          display: "grid", gridTemplateColumns: "2fr 1fr 1.2fr 1fr 0.8fr 1fr 120px",
          padding: "12px 20px", background: c.slate50,
          borderBottom: `1px solid ${c.border}`, fontSize: 11, fontWeight: 700,
          color: c.subtleText, textTransform: "uppercase", letterSpacing: "0.05em",
        }}>
          <div>Document Name</div>
          <div>Category</div>
          <div>Patient</div>
          <div>Date</div>
          <div>Size</div>
          <div>Status</div>
          <div style={{ textAlign: "right" }}>Action</div>
        </div>

        {isLoading ? (
          <div style={{ padding: 40, textAlign: "center", color: c.subtleText, fontSize: 14 }}>
            <RefreshCw size={20} style={{ animation: "spin 1s linear infinite", marginBottom: 8 }} />
            <div>Loading OpenEMR documents…</div>
          </div>
        ) : isError ? (
          <div style={{ padding: 40, textAlign: "center" }}>
            <EmptyState icon={<AlertCircle size={40} color={c.red600} />} title="Failed to load" description="Could not connect to OpenEMR. Check backend connection." />
          </div>
        ) : documents.length === 0 ? (
          <div style={{ padding: 40, textAlign: "center" }}>
            <EmptyState icon={<Database size={40} color={c.slate400} />} title="No documents found" description={patientIdFilter ? "No documents for this patient ID." : "No documents available in OpenEMR."} />
          </div>
        ) : (
          documents.map((doc) => {
            const isPulling = pullingIds.has(doc.openemr_doc_id);
            return (
              <div
                key={doc.openemr_doc_id}
                style={{
                  display: "grid", gridTemplateColumns: "2fr 1fr 1.2fr 1fr 0.8fr 1fr 120px",
                  padding: "14px 20px", borderBottom: `1px solid ${c.slate100}`,
                  alignItems: "center", fontSize: 13, transition: "background 0.15s ease",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = c.slate50; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = c.white; }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                  {fileIcon(doc.mimetype)}
                  <span style={{ fontWeight: 600, color: c.slate900, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{doc.name}</span>
                </div>
                <div style={{ color: c.slate600 }}>{doc.category || "—"}</div>
                <div style={{ color: c.slate700, fontWeight: 500 }}>
                  {doc.patient_name || `Patient #${doc.patient_id}`}
                </div>
                <div style={{ color: c.subtleText }}>{formatDate(doc.date)}</div>
                <div style={{ color: c.subtleText }}>{formatBytes(doc.size)}</div>
                <div>
                  {doc.already_imported ? (
                    <span style={{
                      display: "inline-flex", alignItems: "center", gap: 4,
                      padding: "4px 10px", borderRadius: 14, fontSize: 12, fontWeight: 600,
                      background: c.emerald50, color: c.emerald600,
                    }}>
                      <CheckCircle2 size={12} /> Imported
                    </span>
                  ) : (
                    <span style={{
                      display: "inline-flex", alignItems: "center", gap: 4,
                      padding: "4px 10px", borderRadius: 14, fontSize: 12, fontWeight: 600,
                      background: c.amber50, color: c.amber500,
                    }}>
                      <Clock size={12} /> Not Imported
                    </span>
                  )}
                </div>
                <div style={{ textAlign: "right" }}>
                  {doc.already_imported ? (
                    <span style={{ fontSize: 12, color: c.slate400 }}>—</span>
                  ) : (
                    <button
                      className="btn-press"
                      onClick={() => handlePull(doc.openemr_doc_id)}
                      disabled={isPulling}
                      style={{
                        display: "inline-flex", alignItems: "center", gap: 6,
                        padding: "6px 14px", borderRadius: 8, border: "none",
                        background: isPulling ? c.slate200 : `linear-gradient(135deg, ${c.emerald500} 0%, ${c.emerald600} 100%)`,
                        color: isPulling ? c.slate400 : c.white,
                        fontSize: 12, fontWeight: 600, cursor: isPulling ? "default" : "pointer",
                        transition: "all 0.2s ease",
                      }}
                    >
                      {isPulling ? <RefreshCw size={12} style={{ animation: "spin 1s linear infinite" }} /> : <Download size={12} />}
                      {isPulling ? "Pulling..." : "Pull & Analyze"}
                    </button>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>

      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
    </ErrorBoundary>
  );
}

// ─── Document Table Row ───────────────────────────────────────────────────────

interface DocumentRowProps {
  doc: Document;
  onView: () => void;
  onAnalyze: (id: string) => void;
  onDelete: (id: string) => void;
}

function DocumentRow({ doc, onView, onAnalyze, onDelete }: DocumentRowProps) {
  const [hovered, setHovered] = useState(false);

  return (
    <div
      className="animate-fade-in"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(200px, 2fr) 150px 160px 120px 100px 80px 100px",
        padding: "0 16px",
        height: 56,
        borderBottom: `1px solid ${c.slate100}`,
        alignItems: "center",
        gap: 8,
        background: hovered ? `linear-gradient(135deg, ${tokens.primarySoft} 0%, rgba(245,243,255,0.03) 100%)` : c.white,
        transition: "all 0.2s ease",
        cursor: "pointer",
        borderLeft: hovered ? `3px solid ${c.primary}` : "3px solid transparent",
      }}
      onClick={onView}
      role="row"
      tabIndex={0}
      aria-label={`Document ${doc.filename}`}
      onKeyDown={(e) => e.key === "Enter" && onView()}
    >
      {/* Document name */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
        {fileIcon(doc.file_type)}
        <span
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: c.slate900,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {doc.filename}
        </span>
      </div>

      {/* Type */}
      <span style={{ fontSize: 12, color: c.subtleText, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {doc.document_type}
      </span>

      {/* Patient */}
      <span
        style={{
          fontSize: 12,
          color: doc.patient_name ? c.slate900 : c.slate400,
          fontStyle: doc.patient_name ? "normal" : "italic",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {doc.patient_name || "Unlinked"}
      </span>

      {/* Date */}
      <span style={{ fontSize: 12, color: c.subtleText, whiteSpace: "nowrap" }}>
        {formatDate(doc.encounter_date)}
      </span>

      {/* Status */}
      <StatusBadge status={doc.status} />

      {/* HCCs */}
      <div>
        {doc.hcc_count > 0 ? (
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              padding: "2px 8px",
              borderRadius: 6,
              background: `${c.violet500}1A`,
              color: c.violet500,
              fontSize: 12,
              fontWeight: 700,
            }}
          >
            {doc.hcc_count}
          </span>
        ) : (
          <span style={{ fontSize: 12, color: c.slate400 }}>—</span>
        )}
      </div>

      {/* Actions */}
      <div
        style={{ display: "flex", gap: 6 }}
        onClick={(e) => e.stopPropagation()}
      >
        <button
          className="btn-press"
          onClick={onView}
          title="View results"
          aria-label="View document"
          style={{
            width: 30,
            height: 30,
            borderRadius: 8,
            border: `1px solid ${c.slate200}`,
            background: c.white,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            cursor: "pointer",
            color: c.slate600,
            transition: "all 0.15s ease",
          }}
        >
          <Eye size={13} />
        </button>
        {(doc.status === "uploaded" || doc.status === "error") && (
          <button
            className="btn-press"
            onClick={() => onAnalyze(doc.id)}
            title="Analyze document"
            aria-label="Analyze document"
            style={{
              width: 30,
              height: 30,
              borderRadius: 8,
              border: `1px solid ${c.primary}`,
              background: `linear-gradient(135deg, ${c.primary}15 0%, ${c.primary}08 100%)`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              cursor: "pointer",
              color: c.primary,
              transition: "all 0.15s ease",
            }}
          >
            <Zap size={13} />
          </button>
        )}
        <button
          className="btn-press"
          onClick={() => onDelete(doc.id)}
          title="Delete document"
          aria-label="Delete document"
          style={{
            width: 30,
            height: 30,
            borderRadius: 8,
            border: `1px solid ${c.slate200}`,
            background: c.white,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            cursor: "pointer",
            color: c.red600,
            transition: "all 0.15s ease",
          }}
        >
          <Trash2 size={13} />
        </button>
      </div>
    </div>
  );
}
