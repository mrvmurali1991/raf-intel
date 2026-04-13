"use client";

import { useState, useRef, useCallback, useId } from "react";
import {
  Upload,
  FileText,
  FileCode2,
  AlertCircle,
  CheckCircle2,
  X,
  Loader2,
  ExternalLink,
  Info,
} from "lucide-react";
import { PageHeader, ProgressBar } from "@/components/healthcare-ui";
import { useToast } from "@/components/Toast";
import api from "@/lib/api";

/* ───────────────────────── constants ───────────────────────── */

const ACCEPTED_TYPES: Record<string, { label: string; extensions: string[] }> = {
  "application/pdf": { label: "PDF", extensions: [".pdf"] },
  "text/xml": { label: "C-CDA / XML", extensions: [".xml", ".cda", ".ccda"] },
  "application/xml": { label: "C-CDA / XML", extensions: [".xml", ".cda", ".ccda"] },
};

const ACCEPTED_EXTENSIONS = Object.values(ACCEPTED_TYPES).flatMap((t) => t.extensions);
const ACCEPT_STRING = Object.keys(ACCEPTED_TYPES).join(",") + "," + ACCEPTED_EXTENSIONS.join(",");
const MAX_FILE_SIZE_MB = 50;
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;

const DOCUMENT_TYPES = [
  { value: "", label: "Select document type..." },
  { value: "clinical_note", label: "Clinical Note" },
  { value: "lab_report", label: "Lab Report" },
  { value: "radiology_report", label: "Radiology Report" },
  { value: "discharge_summary", label: "Discharge Summary" },
  { value: "progress_note", label: "Progress Note" },
  { value: "consultation", label: "Consultation" },
  { value: "operative_note", label: "Operative Note" },
  { value: "other", label: "Other" },
];

/* ───────────────────────── design tokens ───────────────────────── */

const colors = {
  primary: "#2563EB",
  slate900: "#0F172A",
  slate600: "#475569",
  slate400: "#94A3B8",
  slate200: "#E2E8F0",
  slate100: "#F1F5F9",
  slate50: "#F8FAFC",
  white: "#FFFFFF",
  red600: "#DC2626",
  red50: "#FEF2F2",
  amber500: "#F59E0B",
  emerald500: "#10B981",
  emerald50: "#ECFDF5",
};

/* ───────────────────────── styles ───────────────────────── */

const card: React.CSSProperties = {
  background: colors.white,
  border: `1px solid ${colors.slate200}`,
  borderRadius: 12,
  padding: 24,
};

const labelStyle: React.CSSProperties = {
  fontSize: 13,
  fontWeight: 600,
  color: "#374151",
  marginBottom: 6,
  display: "block",
};

const inputStyle = (hasError: boolean): React.CSSProperties => ({
  width: "100%",
  padding: "10px 12px",
  fontSize: 14,
  borderRadius: 8,
  border: `1.5px solid ${hasError ? colors.red600 : colors.slate200}`,
  outline: "none",
  background: colors.white,
  color: colors.slate900,
  boxSizing: "border-box",
  transition: "border-color 0.15s",
});

const btnPrimary = (disabled: boolean): React.CSSProperties => ({
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
  padding: "12px 24px",
  fontSize: 14,
  fontWeight: 600,
  borderRadius: 8,
  border: "none",
  background: disabled ? "#94A3B8" : colors.primary,
  color: colors.white,
  cursor: disabled ? "not-allowed" : "pointer",
  transition: "all 0.15s",
});

const errorMsgStyle: React.CSSProperties = {
  fontSize: 12,
  color: colors.red600,
  marginTop: 4,
  display: "flex",
  alignItems: "center",
  gap: 4,
};

/* ───────────────────────── helpers ───────────────────────── */

function isAcceptedFile(file: File): boolean {
  const ext = "." + file.name.split(".").pop()?.toLowerCase();
  return ACCEPTED_EXTENSIONS.includes(ext);
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

function formatTime(date: Date): string {
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/* ───────────────────────── types ───────────────────────── */

interface FieldErrors {
  file?: string;
  documentType?: string;
  encounterDate?: string;
}

interface UploadSuccess {
  filename: string;
  uploadTime: Date;
  documentId?: string | number;
}

/* ───────────────────────── page ───────────────────────── */

export default function UploadsPage() {
  const toast = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const formId = useId();

  // form state
  const [file, setFile] = useState<File | null>(null);
  const [documentType, setDocumentType] = useState("");
  const [encounterDate, setEncounterDate] = useState("");
  const [notes, setNotes] = useState("");

  // validation
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [submitted, setSubmitted] = useState(false);

  // upload state
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [uploadSuccess, setUploadSuccess] = useState<UploadSuccess | null>(null);

  // drag state
  const [dragOver, setDragOver] = useState(false);

  /* ── ids for aria-describedby ── */
  const fileErrorId = `${formId}-file-error`;
  const docTypeErrorId = `${formId}-doctype-error`;
  const dateErrorId = `${formId}-date-error`;

  /* ── file validation ── */
  const validateFile = useCallback((f: File): string | undefined => {
    if (!isAcceptedFile(f)) {
      return `"${f.name}" is not a supported format. Please upload PDF or C-CDA/XML files.`;
    }
    if (f.size > MAX_FILE_SIZE_BYTES) {
      return `File is ${formatFileSize(f.size)} which exceeds the ${MAX_FILE_SIZE_MB}MB limit.`;
    }
    return undefined;
  }, []);

  const handleFileSelect = useCallback(
    (f: File) => {
      const error = validateFile(f);
      if (error) {
        setFieldErrors((prev) => ({ ...prev, file: error }));
        setFile(null);
      } else {
        setFieldErrors((prev) => ({ ...prev, file: undefined }));
        setFile(f);
      }
      setUploadSuccess(null);
    },
    [validateFile]
  );

  /* ── drop handlers ── */
  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const f = e.dataTransfer.files?.[0];
      if (f) handleFileSelect(f);
    },
    [handleFileSelect]
  );

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const onDragLeave = useCallback(() => setDragOver(false), []);

  const onInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const f = e.target.files?.[0];
      if (f) handleFileSelect(f);
      // reset so same file can be re-selected
      e.target.value = "";
    },
    [handleFileSelect]
  );

  /* ── field validation ── */
  const validateAll = useCallback((): FieldErrors => {
    const errors: FieldErrors = {};
    if (!file) errors.file = "Please select a file to upload.";
    if (!documentType) errors.documentType = "Document type is required.";
    if (!encounterDate) errors.encounterDate = "Encounter date is required.";
    return errors;
  }, [file, documentType, encounterDate]);

  /* ── submit ── */
  const handleSubmit = useCallback(async () => {
    setSubmitted(true);
    const errors = validateAll();
    setFieldErrors(errors);

    if (Object.values(errors).some(Boolean)) return;
    if (!file) return;

    setUploading(true);
    setUploadProgress(0);

    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("document_type", documentType);
      formData.append("encounter_date", encounterDate);
      if (notes.trim()) formData.append("notes", notes.trim());

      const { data } = await api.post("/api/documents/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
        onUploadProgress: (progressEvent) => {
          if (progressEvent.total) {
            setUploadProgress(Math.round((progressEvent.loaded / progressEvent.total) * 100));
          } else {
            // indeterminate — pulse between 10-90
            setUploadProgress(-1);
          }
        },
      });

      setUploadSuccess({
        filename: file.name,
        uploadTime: new Date(),
        documentId: data?.id ?? data?.document_id,
      });
      toast.success("Upload complete", `${file.name} uploaded successfully.`);

      // reset form
      setFile(null);
      setDocumentType("");
      setEncounterDate("");
      setNotes("");
      setSubmitted(false);
      setFieldErrors({});
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.message || "Upload failed";
      toast.error("Upload failed", msg);
    } finally {
      setUploading(false);
      setUploadProgress(null);
    }
  }, [file, documentType, encounterDate, notes, validateAll, toast]);

  /* ── clear file ── */
  const clearFile = useCallback(() => {
    setFile(null);
    setFieldErrors((prev) => ({ ...prev, file: undefined }));
    setUploadSuccess(null);
  }, []);

  /* ── collect validation summary ── */
  const validationSummary = submitted
    ? Object.entries(fieldErrors)
        .filter(([, v]) => !!v)
        .map(([k, v]) => ({ field: k, message: v! }))
    : [];

  /* ───────────────────────── render ───────────────────────── */
  return (
    <div style={{ padding: "32px 32px 64px", maxWidth: 720, margin: "0 auto" }}>
      <PageHeader
        title="Upload Document"
        subtitle="Upload clinical documents for HCC coding analysis"
        icon={<Upload size={22} />}
      />

      {/* ── Accepted formats ── */}
      <div
        style={{
          display: "flex",
          gap: 16,
          marginBottom: 20,
          flexWrap: "wrap",
        }}
      >
        <FormatChip icon={<FileText size={16} />} label="PDF" extensions=".pdf" />
        <FormatChip icon={<FileCode2 size={16} />} label="C-CDA / XML" extensions=".xml, .cda, .ccda" />
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontSize: 12,
            color: colors.slate400,
            marginLeft: "auto",
          }}
        >
          <Info size={14} />
          Max file size: {MAX_FILE_SIZE_MB}MB
        </div>
      </div>

      {/* ── Validation summary ── */}
      {validationSummary.length > 0 && (
        <div
          role="alert"
          style={{
            background: colors.red50,
            border: `1px solid ${colors.red600}33`,
            borderRadius: 8,
            padding: "12px 16px",
            marginBottom: 20,
            display: "flex",
            flexDirection: "column",
            gap: 4,
          }}
        >
          <div style={{ fontSize: 13, fontWeight: 600, color: colors.red600, display: "flex", alignItems: "center", gap: 6 }}>
            <AlertCircle size={15} /> Please fix the following errors:
          </div>
          <ul style={{ margin: "4px 0 0 20px", padding: 0, fontSize: 13, color: colors.red600 }}>
            {validationSummary.map((e) => (
              <li key={e.field}>{e.message}</li>
            ))}
          </ul>
        </div>
      )}

      {/* ── Success state ── */}
      {uploadSuccess && (
        <div
          role="status"
          style={{
            background: colors.emerald50,
            border: `1px solid ${colors.emerald500}33`,
            borderRadius: 8,
            padding: "16px 20px",
            marginBottom: 20,
            display: "flex",
            alignItems: "center",
            gap: 12,
          }}
        >
          <CheckCircle2 size={20} style={{ color: colors.emerald500, flexShrink: 0 }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: colors.slate900 }}>Upload successful</div>
            <div style={{ fontSize: 13, color: colors.slate600, marginTop: 2 }}>
              <strong>{uploadSuccess.filename}</strong> &mdash; {formatTime(uploadSuccess.uploadTime)}
            </div>
          </div>
          {uploadSuccess.documentId && (
            <a
              href={`/documents/${uploadSuccess.documentId}`}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                fontSize: 13,
                fontWeight: 600,
                color: colors.primary,
                textDecoration: "none",
              }}
            >
              View Document <ExternalLink size={14} />
            </a>
          )}
        </div>
      )}

      {/* ── Form card ── */}
      <div style={card}>
        {/* ── Drop zone ── */}
        <div
          role="button"
          tabIndex={0}
          aria-label="Upload file drop zone. Click or press Enter to browse files."
          aria-invalid={!!fieldErrors.file}
          aria-describedby={fieldErrors.file ? fileErrorId : undefined}
          onDrop={onDrop}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onClick={() => fileInputRef.current?.click()}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              fileInputRef.current?.click();
            }
          }}
          style={{
            border: `2px dashed ${fieldErrors.file ? colors.red600 : dragOver ? colors.primary : colors.slate200}`,
            borderRadius: 10,
            padding: file ? "16px 20px" : "40px 20px",
            textAlign: "center",
            cursor: "pointer",
            background: dragOver ? `${colors.primary}08` : fieldErrors.file ? colors.red50 : colors.slate50,
            transition: "all 0.15s",
            marginBottom: 20,
          }}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPT_STRING}
            onChange={onInputChange}
            style={{ display: "none" }}
            aria-hidden="true"
          />

          {file ? (
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <FileText size={20} style={{ color: colors.primary, flexShrink: 0 }} />
              <div style={{ flex: 1, textAlign: "left" }}>
                <div style={{ fontSize: 14, fontWeight: 600, color: colors.slate900 }}>{file.name}</div>
                <div style={{ fontSize: 12, color: colors.slate400 }}>{formatFileSize(file.size)}</div>
              </div>
              <button
                type="button"
                aria-label="Remove file"
                onClick={(e) => {
                  e.stopPropagation();
                  clearFile();
                }}
                style={{
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  color: colors.slate400,
                  padding: 4,
                  borderRadius: 4,
                  display: "flex",
                }}
              >
                <X size={18} />
              </button>
            </div>
          ) : (
            <>
              <Upload size={28} style={{ color: colors.slate400, marginBottom: 8 }} />
              <div style={{ fontSize: 14, fontWeight: 600, color: colors.slate900 }}>
                Drop a file here or click to browse
              </div>
              <div style={{ fontSize: 12, color: colors.slate400, marginTop: 4 }}>
                PDF or C-CDA/XML up to {MAX_FILE_SIZE_MB}MB
              </div>
            </>
          )}
        </div>
        {fieldErrors.file && (
          <div id={fileErrorId} style={errorMsgStyle}>
            <AlertCircle size={13} /> {fieldErrors.file}
          </div>
        )}

        {/* ── Upload progress ── */}
        {uploading && (
          <div style={{ marginBottom: 20 }}>
            {uploadProgress !== null && uploadProgress >= 0 ? (
              <ProgressBar value={uploadProgress} label="Uploading..." color={colors.primary} height={8} />
            ) : (
              <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: colors.slate600 }}>
                <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} />
                Uploading...
              </div>
            )}
          </div>
        )}

        {/* ── Document type ── */}
        <div style={{ marginBottom: 16 }}>
          <label htmlFor={`${formId}-doctype`} style={labelStyle}>
            Document Type <span style={{ color: colors.red600 }}>*</span>
          </label>
          <select
            id={`${formId}-doctype`}
            value={documentType}
            onChange={(e) => {
              setDocumentType(e.target.value);
              if (e.target.value) setFieldErrors((prev) => ({ ...prev, documentType: undefined }));
            }}
            aria-invalid={!!fieldErrors.documentType}
            aria-describedby={fieldErrors.documentType ? docTypeErrorId : undefined}
            style={{
              ...inputStyle(!!fieldErrors.documentType),
              appearance: "none",
              backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2394A3B8' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E")`,
              backgroundRepeat: "no-repeat",
              backgroundPosition: "right 12px center",
              paddingRight: 36,
            }}
          >
            {DOCUMENT_TYPES.map((dt) => (
              <option key={dt.value} value={dt.value}>
                {dt.label}
              </option>
            ))}
          </select>
          {fieldErrors.documentType && (
            <div id={docTypeErrorId} style={errorMsgStyle}>
              <AlertCircle size={13} /> {fieldErrors.documentType}
            </div>
          )}
        </div>

        {/* ── Encounter date ── */}
        <div style={{ marginBottom: 16 }}>
          <label htmlFor={`${formId}-date`} style={labelStyle}>
            Encounter Date <span style={{ color: colors.red600 }}>*</span>
          </label>
          <input
            id={`${formId}-date`}
            type="date"
            value={encounterDate}
            onChange={(e) => {
              setEncounterDate(e.target.value);
              if (e.target.value) setFieldErrors((prev) => ({ ...prev, encounterDate: undefined }));
            }}
            aria-invalid={!!fieldErrors.encounterDate}
            aria-describedby={fieldErrors.encounterDate ? dateErrorId : undefined}
            style={inputStyle(!!fieldErrors.encounterDate)}
          />
          {fieldErrors.encounterDate && (
            <div id={dateErrorId} style={errorMsgStyle}>
              <AlertCircle size={13} /> {fieldErrors.encounterDate}
            </div>
          )}
        </div>

        {/* ── Notes (optional) ── */}
        <div style={{ marginBottom: 24 }}>
          <label htmlFor={`${formId}-notes`} style={labelStyle}>
            Notes <span style={{ fontSize: 11, fontWeight: 400, color: colors.slate400 }}>(optional)</span>
          </label>
          <textarea
            id={`${formId}-notes`}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            placeholder="Additional context about this document..."
            style={{
              ...inputStyle(false),
              resize: "vertical",
              fontFamily: "inherit",
            }}
          />
        </div>

        {/* ── Submit ── */}
        <button
          type="button"
          disabled={uploading}
          onClick={handleSubmit}
          style={btnPrimary(uploading)}
        >
          {uploading ? (
            <>
              <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> Uploading...
            </>
          ) : (
            <>
              <Upload size={16} /> Upload Document
            </>
          )}
        </button>
      </div>

      {/* spin keyframes */}
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

/* ───────────────────────── sub-components ───────────────────────── */

function FormatChip({ icon, label, extensions }: { icon: React.ReactNode; label: string; extensions: string }) {
  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "6px 12px",
        borderRadius: 8,
        background: colors.slate50,
        border: `1px solid ${colors.slate200}`,
        fontSize: 13,
        color: colors.slate600,
      }}
    >
      <span style={{ color: colors.primary, display: "flex" }}>{icon}</span>
      <span style={{ fontWeight: 600 }}>{label}</span>
      <span style={{ color: colors.slate400 }}>({extensions})</span>
    </div>
  );
}
