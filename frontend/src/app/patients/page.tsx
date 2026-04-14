"use client";

import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import { ErrorBoundary } from "@/components/error-boundary";
import { FocusTrap } from "@/components/ui/focus-trap";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { searchPatients, isEmrDeactivatedError } from "@/lib/api";
import api from "@/lib/api";
import type { Patient } from "@/types";
import { calculateAge } from "@/lib/utils";
import {
  Users,
  Search,
  ChevronRight,
  ChevronLeft,
  ChevronUp,
  ChevronDown,
  AlertTriangle,
  RefreshCw,
  FileDown,
  FileUp,
  Upload,
  X,
  CheckCircle,
  Download,
  Filter,
  FilterX,
  ShieldCheck,
  Trash2,
  TrendingUp,
  Activity,
} from "lucide-react";
import { downloadCSV } from "@/lib/csv-export";
import { C, FONT_SYS, FONT_MONO, initialsColor, deriveInitials, riskAccentColor, riskTone } from "@/lib/ui-utils";

// ---------------------------------------------------------------------------
// Constants & Types
// ---------------------------------------------------------------------------

const PAGE_SIZE = 20;

type SortKey = "name" | "age" | "raf_score" | "hcc_count";
type SortDir = "asc" | "desc";
type RiskFilter = "all" | "high" | "medium" | "low" | "unscored";

// Worklist grid template — single source of truth so header, body rows,
// skeleton, column-filter row and group super-header all stay perfectly aligned.
// 9 cells: Patient | Age/Sex | RAF Score | Demo | Disease | Interact | HCCs | Status | ›
const WORKLIST_GRID =
  "minmax(280px, 2.6fr) 80px 132px 88px 88px 88px 96px 116px 28px";
const WORKLIST_GAP = 12;
const WORKLIST_PAD_X = 24;
const ROW_HEIGHT = 76;
const SUBSCORE_BAND_BG = C.bgBand;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatLocation(p: Patient): string {
  const parts: string[] = [];
  if (p.city) parts.push(p.city);
  if (p.state) parts.push(p.state);
  if (parts.length === 0 && p.postal_code) return p.postal_code;
  return parts.join(", ") || "\u2014";
}

// ---------------------------------------------------------------------------
// SortLabel
// ---------------------------------------------------------------------------

function SortLabel({
  col,
  label,
  sort,
  onSort,
  align = "left",
}: {
  col: SortKey;
  label: string;
  sort: { key: SortKey; dir: SortDir };
  onSort: (key: SortKey) => void;
  align?: "left" | "right";
}) {
  const active = sort.key === col;
  const ariaSort: "ascending" | "descending" | "none" = active
    ? sort.dir === "asc" ? "ascending" : "descending"
    : "none";
  return (
    <button
      role="columnheader"
      aria-sort={ariaSort}
      aria-label={`Sort by ${label}`}
      onClick={() => onSort(col)}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        background: "none",
        border: "none",
        padding: 0,
        margin: 0,
        cursor: "pointer",
        fontFamily: FONT_SYS,
        fontSize: 11,
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.06em",
        color: active ? C.brand : C.label,
        whiteSpace: "nowrap",
        transition: "color 0.15s ease",
        justifySelf: align === "right" ? "end" : "start",
      }}
    >
      {label}
      <span style={{
        display: "inline-flex",
        flexDirection: "column",
        opacity: active ? 1 : 0.55,
        marginLeft: 2,
      }}>
        <ChevronUp size={9} style={{
          marginBottom: -3,
          color: active && sort.dir === "asc" ? C.brand : "#CBD5E1",
        }} />
        <ChevronDown size={9} style={{
          marginTop: -3,
          color: active && sort.dir === "desc" ? C.brand : "#CBD5E1",
        }} />
      </span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Types for import
// ---------------------------------------------------------------------------

interface ImportSummary {
  total_rows: number;
  imported: number;
  updated: number;
  deleted: number;
  duplicates_skipped: number;
  errors: number;
  error_details: string[];
}

// ---------------------------------------------------------------------------
// ImportCSVModal (unchanged behavior)
// ---------------------------------------------------------------------------

function ImportCSVModal({ onClose, onImported }: { onClose: () => void; onImported: () => void }) {
  const [format, setFormat] = useState<"csv" | "fhir">("csv");
  const [dragOver, setDragOver] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string[][]>([]);
  const [headers, setHeaders] = useState<string[]>([]);
  const [fhirResourceCount, setFhirResourceCount] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<ImportSummary | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [onDuplicate, setOnDuplicate] = useState<"skip" | "update" | "replace">("skip");
  const fileInputRef = useRef<HTMLInputElement>(null);

  function clearFileState() {
    setFile(null);
    setPreview([]);
    setHeaders([]);
    setFhirResourceCount(null);
    setUploadError(null);
    setResult(null);
  }

  function handleFormatSwitch(newFormat: "csv" | "fhir") {
    if (newFormat === format) return;
    setFormat(newFormat);
    clearFileState();
  }

  function parsePreview(text: string) {
    const lines = text.split(/\r?\n/).filter(Boolean);
    if (lines.length === 0) return;
    const header = lines[0].split(",").map((h) => h.trim());
    setHeaders(header);
    const rows = lines.slice(1, 6).map((l) =>
      l.split(",").map((v) => v.trim())
    );
    setPreview(rows);
  }

  function parseFhirPreview(text: string) {
    try {
      const json = JSON.parse(text);
      let count = 0;
      if (json.resourceType === "Bundle" && Array.isArray(json.entry)) {
        count = json.entry.filter(
          (e: { resource?: { resourceType?: string } }) => e?.resource?.resourceType === "Patient"
        ).length;
      } else if (json.resourceType === "Patient") {
        count = 1;
      }
      setFhirResourceCount(count);
    } catch {
      setUploadError("Could not parse JSON. Please upload a valid FHIR R4 Patient resource or Bundle.");
    }
  }

  function handleFileSelect(selected: File | null) {
    if (!selected) return;
    if (format === "csv") {
      const ext = selected.name.toLowerCase();
      if (!ext.endsWith(".csv") && !ext.endsWith(".xlsx")) {
        setUploadError("Only .csv and .xlsx files are accepted.");
        return;
      }
    } else {
      if (!selected.name.toLowerCase().endsWith(".json")) {
        setUploadError("Only .json files are accepted.");
        return;
      }
    }
    setUploadError(null);
    setResult(null);
    setFhirResourceCount(null);
    setPreview([]);
    setHeaders([]);
    setFile(selected);
    const reader = new FileReader();
    if (format === "csv" && !selected.name.toLowerCase().endsWith(".xlsx")) {
      reader.onload = (e) => parsePreview((e.target?.result as string) || "");
    } else if (format === "fhir") {
      reader.onload = (e) => parseFhirPreview((e.target?.result as string) || "");
    }
    if (format !== "csv" || !selected.name.toLowerCase().endsWith(".xlsx")) {
      reader.readAsText(selected);
    }
  }

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragOver(false);
    const dropped = e.dataTransfer.files[0] ?? null;
    handleFileSelect(dropped);
  }

  async function handleImport() {
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    const endpoint = format === "csv"
      ? `/api/patients/import?on_duplicate=${onDuplicate}`
      : `/api/patients/import/fhir?on_duplicate=${onDuplicate}`;
    try {
      const formData = new FormData();
      formData.append("file", file);
      const response = await api.post<ImportSummary>(endpoint, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setResult(response.data);
      if (response.data.imported > 0 || (response.data.deleted ?? 0) > 0) onImported();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string | { message?: string; errors?: string[] } } } })?.response?.data?.detail;
      if (typeof detail === "string") {
        setUploadError(detail);
      } else if (detail?.message) {
        setUploadError(`${detail.message}: ${(detail.errors ?? []).join("; ")}`);
      } else {
        setUploadError("Upload failed. Please check the file and try again.");
      }
    } finally {
      setUploading(false);
    }
  }

  async function handleDownloadTemplate() {
    if (format === "csv") {
      try {
        const response = await api.get("/api/patients/import/template", {
          responseType: "blob",
        });
        const url = URL.createObjectURL(new Blob([response.data], { type: "text/csv" }));
        const a = document.createElement("a");
        a.href = url;
        a.download = "patient_import_template.csv";
        a.click();
        URL.revokeObjectURL(url);
      } catch {
        const cols = "first_name,middle_name,last_name,previous_name,dob,sex,birth_sex,gender_identity,sexual_orientation,pronouns,ssn,phone,email,address,city,state,zip,race,ethnicity,preferred_language,mrn,mbi,insurance_type,emergency_contact_name,emergency_contact_phone";
        const example = "Jane,Marie,Doe,,1980-04-15,Female,Female,Woman,Straight or Heterosexual,she/her,,,jane.doe@example.com,123 Main St,Springfield,IL,62701,White,Not Hispanic or Latino,English,MRN00001,,Medicare,,";
        const blob = new Blob([`${cols}\n${example}\n`], { type: "text/csv" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "patient_import_template.csv";
        a.click();
        URL.revokeObjectURL(url);
      }
    } else {
      try {
        const response = await api.get("/api/patients/import/template/fhir", {
          responseType: "blob",
        });
        const url = URL.createObjectURL(new Blob([response.data], { type: "application/json" }));
        const a = document.createElement("a");
        a.href = url;
        a.download = "patient_import_template_fhir.json";
        a.click();
        URL.revokeObjectURL(url);
      } catch {
        const template = {
          resourceType: "Bundle",
          type: "collection",
          entry: [
            {
              resource: {
                resourceType: "Patient",
                id: "example-patient-1",
                name: [{ use: "official", family: "Doe", given: ["Jane", "Marie"] }],
                birthDate: "1980-04-15",
                gender: "female",
                telecom: [
                  { system: "phone", value: "555-867-5309", use: "home" },
                  { system: "email", value: "jane.doe@example.com" },
                ],
                address: [
                  { line: ["123 Main St"], city: "Springfield", state: "IL", postalCode: "62701" },
                ],
                identifier: [
                  { system: "http://terminology.hl7.org/CodeSystem/v2-0203", type: { coding: [{ code: "MR" }] }, value: "MRN00001" },
                ],
              },
            },
          ],
        };
        const blob = new Blob([JSON.stringify(template, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "patient_import_template_fhir.json";
        a.click();
        URL.revokeObjectURL(url);
      }
    }
  }

  const OVERLAY: React.CSSProperties = {
    position: "fixed", inset: 0, zIndex: 1000,
    backgroundColor: "rgba(15, 23, 42, 0.55)",
    display: "flex", alignItems: "center", justifyContent: "center",
    padding: 24,
  };

  const MODAL: React.CSSProperties = {
    backgroundColor: "#FFFFFF",
    borderRadius: 20,
    padding: 32,
    width: "100%",
    maxWidth: 640,
    maxHeight: "90vh",
    overflowY: "auto",
    boxShadow: "0 25px 60px rgba(15, 23, 42, 0.25)",
    display: "flex",
    flexDirection: "column",
    gap: 20,
  };

  return (
    <div style={OVERLAY} onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <FocusTrap>
        <div style={MODAL} role="dialog" aria-modal="true" aria-label="Import patients">
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: "#0F172A" }}>Import Patients</h2>
            <p style={{ margin: "4px 0 0", fontSize: 14, color: "#64748B" }}>
              {format === "csv"
                ? "Upload a CSV file to bulk-import patients into OpenEMR."
                : "Upload a FHIR R4 Patient resource or Bundle to import patients."}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            style={{ background: "none", border: "none", padding: 4, cursor: "pointer", color: "#94A3B8", borderRadius: 8 }}
          >
            <X size={20} />
          </button>
        </div>

        <div style={{
          display: "inline-flex", alignItems: "center",
          backgroundColor: "#F1F5F9", borderRadius: 10, padding: 4, gap: 2,
          alignSelf: "flex-start",
        }}>
          {(["csv", "fhir"] as const).map((f) => (
            <button
              key={f}
              onClick={() => handleFormatSwitch(f)}
              style={{
                padding: "5px 18px", borderRadius: 7, border: "none",
                fontSize: 13, fontWeight: 600, cursor: "pointer",
                transition: "all 0.15s ease",
                backgroundColor: format === f ? "#0f766e" : "transparent",
                color: format === f ? "#FFFFFF" : "#64748B",
                boxShadow: format === f ? "0 2px 6px rgba(15,118,110,0.25)" : "none",
              }}
              aria-pressed={format === f}
            >
              {f === "csv" ? "CSV" : "FHIR JSON"}
            </button>
          ))}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button
            onClick={handleDownloadTemplate}
            style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              padding: "7px 14px", borderRadius: 8,
              border: "1px solid rgba(15, 118, 110, 0.3)",
              backgroundColor: "rgba(15, 118, 110, 0.06)",
              color: "#0f766e", fontSize: 13, fontWeight: 600, cursor: "pointer",
            }}
          >
            <Download size={14} /> {format === "csv" ? "Download Template" : "Download FHIR Template"}
          </button>
          {format === "csv" && (
            <button
              onClick={async () => {
                try {
                  const response = await api.get("/api/patients/import/template/excel", { responseType: "arraybuffer" });
                  const url = URL.createObjectURL(new Blob([response.data], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }));
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = "patient_import_template.xlsx";
                  a.click();
                  URL.revokeObjectURL(url);
                } catch {
                  alert("Failed to download Excel template.");
                }
              }}
              style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                padding: "7px 14px", borderRadius: 8,
                border: "1px solid rgba(15, 118, 110, 0.3)",
                backgroundColor: "rgba(15, 118, 110, 0.06)",
                color: "#0f766e", fontSize: 13, fontWeight: 600, cursor: "pointer",
              }}
            >
              <Download size={14} /> Download Excel Template
            </button>
          )}
          <span style={{ fontSize: 12, color: "#94A3B8" }}>
            {format === "csv"
              ? "Required columns: first_name, last_name, dob, sex (CSV or Excel)"
              : "FHIR R4 Patient resource or Bundle"}
          </span>
        </div>

        {!result && (
          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            style={{
              border: `2px dashed ${dragOver ? "#0f766e" : file ? "#10B981" : "#CBD5E1"}`,
              borderRadius: 14,
              padding: "32px 24px",
              textAlign: "center",
              cursor: "pointer",
              backgroundColor: dragOver ? "rgba(15, 118, 110, 0.04)" : file ? "rgba(16, 185, 129, 0.04)" : "#F8FAFC",
              transition: "all 0.2s ease",
            }}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept={format === "csv" ? ".csv,.xlsx,.xls" : ".json"}
              style={{ display: "none" }}
              onChange={(e) => handleFileSelect(e.target.files?.[0] ?? null)}
            />
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
              <div style={{
                width: 48, height: 48, borderRadius: 12,
                backgroundColor: file ? "rgba(16, 185, 129, 0.12)" : "rgba(15, 118, 110, 0.1)",
                display: "flex", alignItems: "center", justifyContent: "center",
              }}>
                {file ? <CheckCircle size={24} color="#10B981" /> : <Upload size={24} color="#0f766e" />}
              </div>
              {file ? (
                <>
                  <p style={{ margin: 0, fontSize: 14, fontWeight: 600, color: "#0F172A" }}>{file.name}</p>
                  <p style={{ margin: 0, fontSize: 12, color: "#64748B" }}>
                    {(file.size / 1024).toFixed(1)} KB — click to change
                  </p>
                </>
              ) : (
                <>
                  <p style={{ margin: 0, fontSize: 14, fontWeight: 600, color: "#0F172A" }}>
                    {format === "csv"
                      ? "Drop a CSV or Excel file here or click to browse"
                      : "Drop a FHIR JSON file here or click to browse"}
                  </p>
                  <p style={{ margin: 0, fontSize: 12, color: "#94A3B8" }}>
                    {format === "csv"
                      ? "Accepts .csv and .xlsx files up to 10 MB"
                      : "Accepts .json files up to 10 MB"}
                  </p>
                </>
              )}
            </div>
          </div>
        )}

        {file && !result && (
          <div>
            <p style={{ margin: "0 0 10px", fontSize: 13, fontWeight: 600, color: "#475569" }}>
              If a patient already exists in the system:
            </p>
            <div style={{ display: "flex", gap: 10 }}>
              {([
                { key: "skip" as const, icon: ShieldCheck, label: "Skip existing", desc: "Keep existing patient records unchanged. Only new patients are imported." },
                { key: "update" as const, icon: RefreshCw, label: "Update existing", desc: "Update existing patients with new data from your file. New patients are also added." },
                { key: "replace" as const, icon: Trash2, label: "Replace all", desc: "Remove all existing patients and import only the patients from your file." },
              ]).map(({ key, icon: Icon, label, desc }) => (
                <button
                  key={key}
                  onClick={() => setOnDuplicate(key)}
                  style={{
                    flex: 1,
                    padding: "14px 16px",
                    borderRadius: 10,
                    border: `2px solid ${onDuplicate === key ? (key === "replace" ? "#DC2626" : "#0f766e") : "#E2E8F0"}`,
                    backgroundColor: onDuplicate === key ? (key === "replace" ? "rgba(220, 38, 38, 0.05)" : "rgba(15, 118, 110, 0.05)") : "#FFFFFF",
                    cursor: "pointer",
                    textAlign: "left",
                    transition: "border-color 0.15s, background-color 0.15s",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                    <Icon size={16} color={onDuplicate === key ? (key === "replace" ? "#DC2626" : "#0f766e") : "#94A3B8"} />
                    <span style={{ fontSize: 13, fontWeight: 700, color: onDuplicate === key ? (key === "replace" ? "#DC2626" : "#0f766e") : "#0F172A" }}>
                      {label}
                    </span>
                  </div>
                  <p style={{ margin: 0, fontSize: 12, color: "#64748B", lineHeight: 1.4 }}>
                    {desc}
                  </p>
                </button>
              ))}
            </div>
            {onDuplicate === "replace" && (
              <div style={{ marginTop: 8, padding: "8px 12px", borderRadius: 8, backgroundColor: "rgba(220, 38, 38, 0.08)", border: "1px solid #FECACA" }}>
                <p style={{ margin: 0, fontSize: 12, color: "#DC2626", fontWeight: 600 }}>
                  Warning: This will permanently delete all existing patients before importing.
                </p>
              </div>
            )}
          </div>
        )}

        {uploadError && (
          <div style={{
            padding: "12px 16px", borderRadius: 10,
            backgroundColor: "#FEF2F2", border: "1px solid #FECACA",
            color: "#991B1B", fontSize: 13,
          }}>
            <strong>Error: </strong>{uploadError}
          </div>
        )}

        {file && format === "csv" && file.name.toLowerCase().endsWith(".xlsx") && !result && (
          <div style={{
            padding: "14px 18px", borderRadius: 10,
            backgroundColor: "rgba(15, 118, 110, 0.06)",
            border: "1px solid rgba(15, 118, 110, 0.25)",
            display: "flex", alignItems: "center", gap: 10,
          }}>
            <CheckCircle size={18} color="#0f766e" />
            <span style={{ fontSize: 14, fontWeight: 600, color: "#0f766e" }}>
              Excel file selected: {file.name} ({(file.size / 1024).toFixed(1)} KB)
            </span>
          </div>
        )}

        {file && format === "csv" && headers.length > 0 && !result && (
          <div>
            <p style={{ margin: "0 0 8px", fontSize: 13, fontWeight: 600, color: "#475569" }}>
              Preview (first 5 rows)
            </p>
            <div style={{ overflowX: "auto", borderRadius: 10, border: "1px solid #E2E8F0" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr style={{ backgroundColor: "#F8FAFC" }}>
                    {headers.map((h) => (
                      <th key={h} style={{
                        padding: "8px 12px", textAlign: "left",
                        fontWeight: 600, color: "#64748B",
                        borderBottom: "1px solid #E2E8F0",
                        whiteSpace: "nowrap",
                      }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.map((row, ri) => (
                    <tr key={ri} style={{ borderBottom: ri < preview.length - 1 ? "1px solid #F1F5F9" : "none" }}>
                      {headers.map((_, ci) => (
                        <td key={ci} style={{ padding: "7px 12px", color: "#0F172A", whiteSpace: "nowrap" }}>
                          {row[ci] ?? ""}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {file && format === "fhir" && fhirResourceCount !== null && !result && (
          <div style={{
            padding: "14px 18px", borderRadius: 10,
            backgroundColor: fhirResourceCount > 0 ? "rgba(15, 118, 110, 0.06)" : "#FEF2F2",
            border: `1px solid ${fhirResourceCount > 0 ? "rgba(15, 118, 110, 0.25)" : "#FECACA"}`,
            display: "flex", alignItems: "center", gap: 10,
          }}>
            <CheckCircle size={18} color={fhirResourceCount > 0 ? "#0f766e" : "#DC2626"} />
            <span style={{ fontSize: 14, fontWeight: 600, color: fhirResourceCount > 0 ? "#0f766e" : "#991B1B" }}>
              {fhirResourceCount > 0
                ? `Found ${fhirResourceCount} Patient resource${fhirResourceCount === 1 ? "" : "s"}`
                : "No Patient resources found in this file"}
            </span>
          </div>
        )}

        {result && (
          <div style={{
            padding: "20px 24px", borderRadius: 14,
            backgroundColor: result.errors > 0 ? "#FFFBEB" : "#F0FDF4",
            border: `1px solid ${result.errors > 0 ? "#FDE68A" : "#BBF7D0"}`,
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}>
              <CheckCircle size={20} color={result.errors > 0 ? "#D97706" : "#059669"} />
              <span style={{ fontSize: 15, fontWeight: 700, color: "#0F172A" }}>Import Complete</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: onDuplicate === "replace" ? "1fr 1fr 1fr 1fr" : "1fr 1fr 1fr 1fr 1fr", gap: 12, marginBottom: result.error_details.length > 0 ? 16 : 0 }}>
              {[
                { label: "Total Rows", value: result.total_rows, color: "#475569" },
                ...(onDuplicate === "replace" ? [{ label: "Deleted (old)", value: result.deleted ?? 0, color: "#DC2626" }] : []),
                { label: "Imported", value: result.imported, color: "#059669" },
                ...(onDuplicate !== "replace" ? [{ label: "Updated", value: result.updated, color: "#0891B2" }] : []),
                ...(onDuplicate !== "replace" ? [{ label: onDuplicate === "update" ? "Unchanged" : "Skipped (dup)", value: result.duplicates_skipped, color: "#64748B" }] : []),
                { label: "Errors", value: result.errors, color: result.errors > 0 ? "#DC2626" : "#94A3B8" },
              ].map(({ label, value, color }) => (
                <div key={label} style={{ textAlign: "center" }}>
                  <div style={{ fontSize: 22, fontWeight: 700, color, fontVariantNumeric: "tabular-nums" }}>{value}</div>
                  <div style={{ fontSize: 11, color: "#94A3B8", marginTop: 2 }}>{label}</div>
                </div>
              ))}
            </div>
            {result.error_details.length > 0 && (
              <div style={{
                maxHeight: 140, overflowY: "auto", padding: "10px 12px",
                backgroundColor: "rgba(255,255,255,0.7)", borderRadius: 8,
                border: "1px solid #FDE68A",
              }}>
                {result.error_details.map((e, i) => (
                  <p key={`err-${i}`} style={{ margin: "0 0 4px", fontSize: 12, color: "#92400E" }}>{e}</p>
                ))}
              </div>
            )}
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
          <button
            onClick={onClose}
            style={{
              padding: "9px 20px", borderRadius: 10,
              border: "1px solid #E2E8F0", backgroundColor: "#FFFFFF",
              fontSize: 14, fontWeight: 500, color: "#475569", cursor: "pointer",
            }}
          >
            {result ? "Close" : "Cancel"}
          </button>
          {!result && (
            <button
              onClick={handleImport}
              disabled={!file || uploading}
              style={{
                padding: "9px 22px", borderRadius: 10,
                border: "none",
                backgroundColor: !file || uploading ? "#94A3B8" : "#0f766e",
                color: "#FFFFFF", fontSize: 14, fontWeight: 600,
                cursor: !file || uploading ? "not-allowed" : "pointer",
                display: "inline-flex", alignItems: "center", gap: 7,
                boxShadow: !file || uploading ? "none" : "0 4px 10px rgba(15,118,110,0.2)",
              }}
            >
              {uploading ? (
                <>
                  <span style={{
                    width: 14, height: 14, borderRadius: "50%",
                    border: "2px solid rgba(255,255,255,0.3)",
                    borderTopColor: "#fff",
                    display: "inline-block",
                    animation: "spin 0.7s linear infinite",
                  }} />
                  Importing…
                </>
              ) : (
                <><Upload size={14} /> Import Patients</>
              )}
            </button>
          )}
        </div>
      </div>
      </FocusTrap>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page component
// ---------------------------------------------------------------------------

export default function PatientsPage() {
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const searchParams = useSearchParams();
  const initialRisk = (searchParams.get("risk") as RiskFilter) || "all";
  const [riskFilter, setRiskFilter] = useState<RiskFilter>(
    ["all", "high", "medium", "low", "unscored"].includes(initialRisk) ? initialRisk : "all"
  );
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({ key: "name", dir: "asc" });
  const [page, setPage] = useState(0);
  const [hoveredRow, setHoveredRow] = useState<string | number | null>(null);
  const [showImportModal, setShowImportModal] = useState(false);
  const [showColumnFilters, setShowColumnFilters] = useState(false);
  const [measurementYear, setMeasurementYear] = useState<number>(2026);
  const [colFilters, setColFilters] = useState({
    sex: "all" as "all" | "Male" | "Female",
    ageMin: "",
    ageMax: "",
    rafMin: "",
    rafMax: "",
    demoMin: "",
    demoMax: "",
    diseaseMin: "",
    diseaseMax: "",
    interactMin: "",
    interactMax: "",
    hccMin: "",
    hccMax: "",
    status: "all" as "all" | "analyzed" | "pending",
  });
  const hasActiveColFilters = colFilters.sex !== "all" || colFilters.ageMin || colFilters.ageMax || colFilters.rafMin || colFilters.rafMax || colFilters.demoMin || colFilters.demoMax || colFilters.diseaseMin || colFilters.diseaseMax || colFilters.interactMin || colFilters.interactMax || colFilters.hccMin || colFilters.hccMax || colFilters.status !== "all";
  const clearColFilters = () => setColFilters({ sex: "all", ageMin: "", ageMax: "", rafMin: "", rafMax: "", demoMin: "", demoMax: "", diseaseMin: "", diseaseMax: "", interactMin: "", interactMax: "", hccMin: "", hccMax: "", status: "all" });
  const router = useRouter();

  // Server-side search & pagination
  const { data: apiResult, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["patients", debouncedSearch, page, riskFilter, hasActiveColFilters, measurementYear],
    queryFn: () => searchPatients({
      search: debouncedSearch || undefined,
      limit: (riskFilter !== "all" || hasActiveColFilters) ? 500 : PAGE_SIZE,
      offset: (riskFilter !== "all" || hasActiveColFilters) ? 0 : page * PAGE_SIZE,
      year: measurementYear,
    }),
    placeholderData: (prev) => prev,
    staleTime: 60_000,
  });

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search);
      setPage(0);
    }, 400);
    return () => clearTimeout(timer);
  }, [search]);

  const { rows, total, totalPages } = useMemo(() => {
    let list: Patient[] = apiResult?.patients ?? [];
    const serverTotal = apiResult?.total ?? 0;

    if (riskFilter !== "all") {
      list = list.filter((p) => {
        const s = p.raf_score ?? 0;
        if (riskFilter === "high") return s >= 2.0;
        if (riskFilter === "medium") return s >= 1.0 && s <= 2.0;
        if (riskFilter === "low") return s > 0 && s < 1.0;
        if (riskFilter === "unscored") return !s || s === 0;
        return true;
      });
    }

    if (colFilters.sex !== "all") {
      list = list.filter((p) => p.sex === colFilters.sex);
    }
    if (colFilters.ageMin) {
      const min = Number(colFilters.ageMin);
      list = list.filter((p) => (p.DOB ? (calculateAge(p.DOB) ?? 0) : 0) >= min);
    }
    if (colFilters.ageMax) {
      const max = Number(colFilters.ageMax);
      list = list.filter((p) => (p.DOB ? (calculateAge(p.DOB) ?? 0) : 999) <= max);
    }
    if (colFilters.rafMin) {
      const min = Number(colFilters.rafMin);
      list = list.filter((p) => (p.raf_score ?? 0) >= min);
    }
    if (colFilters.rafMax) {
      const max = Number(colFilters.rafMax);
      list = list.filter((p) => (p.raf_score ?? 0) <= max);
    }
    if (colFilters.demoMin) {
      const min = Number(colFilters.demoMin);
      list = list.filter((p) => (p.demographic_score ?? 0) >= min);
    }
    if (colFilters.demoMax) {
      const max = Number(colFilters.demoMax);
      list = list.filter((p) => (p.demographic_score ?? 0) <= max);
    }
    if (colFilters.diseaseMin) {
      const min = Number(colFilters.diseaseMin);
      list = list.filter((p) => (p.disease_score ?? 0) >= min);
    }
    if (colFilters.diseaseMax) {
      const max = Number(colFilters.diseaseMax);
      list = list.filter((p) => (p.disease_score ?? 0) <= max);
    }
    if (colFilters.interactMin) {
      const min = Number(colFilters.interactMin);
      list = list.filter((p) => (p.interaction_score ?? 0) >= min);
    }
    if (colFilters.interactMax) {
      const max = Number(colFilters.interactMax);
      list = list.filter((p) => (p.interaction_score ?? 0) <= max);
    }
    if (colFilters.hccMin) {
      const min = Number(colFilters.hccMin);
      list = list.filter((p) => (p.hcc_count ?? 0) >= min);
    }
    if (colFilters.hccMax) {
      const max = Number(colFilters.hccMax);
      list = list.filter((p) => (p.hcc_count ?? 0) <= max);
    }
    if (colFilters.status !== "all") {
      list = list.filter((p) => {
        const scored = (p.raf_score ?? 0) > 0;
        return colFilters.status === "analyzed" ? scored : !scored;
      });
    }

    list = [...list].sort((a, b) => {
      let aVal: string | number, bVal: string | number;
      switch (sort.key) {
        case "name":
          aVal = `${a.lname} ${a.fname}`.toLowerCase();
          bVal = `${b.lname} ${b.fname}`.toLowerCase();
          break;
        case "age":
          aVal = a.DOB ? (calculateAge(a.DOB) ?? 0) : 0;
          bVal = b.DOB ? (calculateAge(b.DOB) ?? 0) : 0;
          break;
        case "raf_score":
          aVal = a.raf_score ?? 0;
          bVal = b.raf_score ?? 0;
          break;
        case "hcc_count":
          aVal = a.hcc_count ?? 0;
          bVal = b.hcc_count ?? 0;
          break;
        default:
          aVal = 0;
          bVal = 0;
      }
      if (aVal < bVal) return sort.dir === "asc" ? -1 : 1;
      if (aVal > bVal) return sort.dir === "asc" ? 1 : -1;
      return 0;
    });

    const clientFiltered = riskFilter !== "all" || hasActiveColFilters;
    const total = clientFiltered ? list.length : serverTotal;
    const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    const rows = clientFiltered ? list.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE) : list;
    return { rows, total, totalPages };
  }, [apiResult, riskFilter, sort, colFilters, hasActiveColFilters, page]);

  const totalPatients = apiResult?.total ?? 0;

  // Risk + summary stats from currently loaded data
  const stats = useMemo(() => {
    const all = apiResult?.patients ?? [];
    let high = 0, medium = 0, low = 0, unscored = 0;
    let rafSum = 0, rafCount = 0, hccSum = 0;
    for (const p of all) {
      const s = p.raf_score ?? 0;
      if (!s || s === 0) unscored++;
      else if (s >= 2.0) high++;
      else if (s >= 1.0) medium++;
      else low++;
      if (s > 0) { rafSum += s; rafCount++; }
      hccSum += p.hcc_count ?? 0;
    }
    return {
      high, medium, low, unscored,
      all: all.length,
      avgRaf: rafCount > 0 ? rafSum / rafCount : 0,
      analyzedPct: all.length > 0 ? Math.round(((all.length - unscored) / all.length) * 100) : 0,
      hccTotal: hccSum,
    };
  }, [apiResult]);

  const handleSort = useCallback((key: SortKey) => {
    setSort((prev) => ({
      key,
      dir: prev.key === key && prev.dir === "asc" ? "desc" : "asc",
    }));
    setPage(0);
  }, []);

  function exportPatientsCSV() {
    if (!rows.length) return;
    const data = rows.map((p) => ({
      "Name": `${p.lname}, ${p.fname}`,
      "PID": p.pid,
      "DOB": p.DOB ?? "",
      "Age": p.DOB ? (calculateAge(p.DOB) ?? "") : "",
      "Sex": p.sex ?? "",
      "Location": formatLocation(p),
      "RAF Score": p.raf_score != null ? Number(p.raf_score).toFixed(2) : "",
      "HCC Count": p.hcc_count ?? 0,
      "Status": (p.raf_score ?? 0) > 0 ? "Analyzed" : "Pending",
    }));
    downloadCSV(data, "patients");
  }

  // ---- EMR deactivated empty state ----
  // The global EmrDeactivatedBanner already tells the user what to do, so
  // here we just render a calm empty state instead of a red "Failed to load"
  // error toast. The banner handles navigation to /emr-config.
  if (isError && isEmrDeactivatedError(error)) {
    return (
      <div role="status" style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "60vh", gap: 16, fontFamily: FONT_SYS }}>
        <div style={{ borderRadius: 16, backgroundColor: "#FEF3C7", padding: 20 }}>
          <AlertTriangle size={40} color="#D97706" />
        </div>
        <h2 style={{ fontSize: 18, fontWeight: 700, color: C.text, margin: 0 }}>No patient data available</h2>
        <p style={{ fontSize: 14, color: C.textSubtle, margin: 0, maxWidth: 440, textAlign: "center" }}>
          Connect an EMR or upload a CSV/Excel file of patients to get started.
        </p>
        <div style={{ display: "flex", gap: 10, marginTop: 8 }}>
          <button
            type="button"
            onClick={() => router.push("/uploads")}
            style={{
              display: "inline-flex", alignItems: "center", gap: 8,
              borderRadius: 10, border: `1px solid ${C.brand}`, backgroundColor: C.brand,
              padding: "8px 16px", fontSize: 14, fontWeight: 600, color: "#FFFFFF",
              cursor: "pointer",
            }}
          >
            <Upload size={16} /> Upload a patient file
          </button>
          <button
            type="button"
            onClick={() => router.push("/emr-config")}
            style={{
              display: "inline-flex", alignItems: "center", gap: 8,
              borderRadius: 10, border: `1px solid ${C.border}`, backgroundColor: "#FFFFFF",
              padding: "8px 16px", fontSize: 14, fontWeight: 500, color: C.textMuted,
              cursor: "pointer",
            }}
          >
            Go to EMR Configuration
          </button>
        </div>
      </div>
    );
  }

  // ---- Error state ----
  if (isError) {
    return (
      <div role="alert" style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "60vh", gap: 16, fontFamily: FONT_SYS }}>
        <div style={{ borderRadius: 16, backgroundColor: "#FEF2F2", padding: 20 }}>
          <AlertTriangle size={40} color="#EF4444" />
        </div>
        <h2 style={{ fontSize: 18, fontWeight: 700, color: C.text, margin: 0 }}>Failed to load patients</h2>
        <p style={{ fontSize: 14, color: C.textSubtle, margin: 0 }}>Check that the server is running and try again.</p>
        <button
          onClick={() => refetch()}
          style={{
            display: "inline-flex", alignItems: "center", gap: 8,
            borderRadius: 10, border: `1px solid ${C.border}`, backgroundColor: "#FFFFFF",
            padding: "8px 16px", fontSize: 14, fontWeight: 500, color: C.textMuted,
            cursor: "pointer",
          }}
        >
          <RefreshCw size={16} /> Retry
        </button>
      </div>
    );
  }

  // ---- Reusable bits ----

  // Per-cell styles for the sub-score band so header / rows / skeleton stay aligned.
  const bandCellStyle = (
    pos: "left" | "mid" | "right",
    bg: string = SUBSCORE_BAND_BG,
    height: number = ROW_HEIGHT,
  ): React.CSSProperties => ({
    height,
    marginLeft: pos === "left" ? -WORKLIST_GAP / 2 - 2 : -WORKLIST_GAP / 2,
    marginRight: pos === "right" ? -WORKLIST_GAP / 2 - 2 : -WORKLIST_GAP / 2,
    paddingLeft: pos === "left" ? 12 : 8,
    paddingRight: pos === "right" ? 12 : 8,
    backgroundColor: bg,
    borderRadius:
      pos === "left" ? "10px 0 0 10px" :
      pos === "right" ? "0 10px 10px 0" :
      undefined,
    display: "flex",
    alignItems: "center",
    justifyContent: "flex-end",
    transition: "background-color 0.2s ease",
  });

  return (
    <ErrorBoundary fallbackTitle="Patients page failed to load">
    <div style={{
      display: "flex", flexDirection: "column", gap: 0,
      background: C.bgPage, minHeight: "100vh",
      padding: "32px 40px 48px",
      fontFamily: FONT_SYS,
      color: C.text,
    }}>
      {/* ============================================================ */}
      {/* Page header                                                  */}
      {/* ============================================================ */}
      <div style={{
        display: "flex", alignItems: "flex-start", justifyContent: "space-between",
        gap: 24, marginBottom: 24,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, minWidth: 0 }}>
          <div style={{
            width: 48, height: 48, borderRadius: 14,
            background: "linear-gradient(135deg, #0F766E 0%, #134E4A 100%)",
            display: "flex", alignItems: "center", justifyContent: "center",
            boxShadow: "0 6px 16px rgba(15, 118, 110, 0.25), inset 0 1px 0 rgba(255,255,255,0.18)",
            flexShrink: 0,
          }}>
            <Users size={22} color="#FFFFFF" strokeWidth={2.25} />
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <h1 style={{
                margin: 0,
                fontSize: 24,
                fontWeight: 700,
                color: C.text,
                letterSpacing: "-0.02em",
                lineHeight: 1.15,
              }}>
                Patient Population
              </h1>
              <div style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                height: 26, padding: "0 4px 0 10px",
                borderRadius: 8,
                backgroundColor: C.brandSoft,
                border: `1px solid ${C.brandRing}`,
                color: C.brand,
                fontSize: 11, fontWeight: 600,
                letterSpacing: "0.02em",
                fontVariantNumeric: "tabular-nums",
              }}>
                <span>MY</span>
                <select
                  value={measurementYear}
                  onChange={(e) => { setMeasurementYear(Number(e.target.value)); setPage(0); }}
                  aria-label="Measurement year"
                  style={{
                    appearance: "none",
                    WebkitAppearance: "none",
                    MozAppearance: "none",
                    background: "transparent",
                    border: "none",
                    color: C.brand,
                    fontSize: 12,
                    fontWeight: 700,
                    fontFamily: FONT_SYS,
                    fontVariantNumeric: "tabular-nums",
                    letterSpacing: "0.01em",
                    cursor: "pointer",
                    padding: "0 18px 0 2px",
                    outline: "none",
                    backgroundImage:
                      "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10' viewBox='0 0 20 20' fill='%230F766E'><path d='M5 8l5 5 5-5H5z'/></svg>\")",
                    backgroundRepeat: "no-repeat",
                    backgroundPosition: "right 2px center",
                  }}
                >
                  {[2024, 2025, 2026].map((y) => (
                    <option key={y} value={y}>{y}</option>
                  ))}
                </select>
              </div>
            </div>
            <p style={{
              margin: "4px 0 0",
              fontSize: 13,
              color: C.textSubtle,
              fontVariantNumeric: "tabular-nums",
            }}>
              {isLoading
                ? "Loading registry…"
                : `${totalPatients.toLocaleString()} patients in registry · CMS-HCC V28 · MY ${measurementYear}`}
            </p>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
          <div style={{ position: "relative" }}>
            <Search
              size={16}
              style={{ position: "absolute", left: 14, top: "50%", transform: "translateY(-50%)", color: C.label, pointerEvents: "none" }}
            />
            <input
              type="text"
              title="Search patients by name or PID"
              placeholder="Search patients…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search patients"
              style={{
                height: 40, width: 320, borderRadius: 10,
                border: `1px solid ${C.border}`,
                backgroundColor: "#FFFFFF",
                paddingLeft: 38, paddingRight: 14,
                fontSize: 13, color: C.text,
                fontFamily: FONT_SYS,
                outline: "none",
                transition: "border-color 0.15s, box-shadow 0.15s",
              }}
              onFocus={(e) => {
                e.currentTarget.style.borderColor = C.brand;
                e.currentTarget.style.boxShadow = `0 0 0 3px ${C.brandSoft}`;
              }}
              onBlur={(e) => {
                e.currentTarget.style.borderColor = C.border;
                e.currentTarget.style.boxShadow = "none";
              }}
            />
          </div>
          <button
            onClick={() => setShowImportModal(true)}
            aria-label="Import patients from CSV"
            style={{
              display: "inline-flex", alignItems: "center", gap: 7,
              height: 40, padding: "0 14px", borderRadius: 10,
              border: `1px solid ${C.border}`,
              backgroundColor: "#FFFFFF",
              color: C.textMuted, fontSize: 13, fontWeight: 600,
              fontFamily: FONT_SYS,
              cursor: "pointer", flexShrink: 0,
              transition: "all 0.15s ease",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = C.brand;
              e.currentTarget.style.color = C.brand;
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = C.border;
              e.currentTarget.style.color = C.textMuted;
            }}
          >
            <FileUp size={14} />
            Import
          </button>
          <button
            onClick={exportPatientsCSV}
            aria-label="Export patients as CSV"
            style={{
              display: "inline-flex", alignItems: "center", gap: 7,
              height: 40, padding: "0 16px", borderRadius: 10,
              border: "none", backgroundColor: C.brand,
              color: "#FFFFFF", fontSize: 13, fontWeight: 600,
              fontFamily: FONT_SYS,
              cursor: "pointer", flexShrink: 0,
              boxShadow: "0 1px 2px rgba(15, 118, 110, 0.25), 0 4px 12px rgba(15, 118, 110, 0.18)",
              transition: "all 0.15s ease",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = "#0d6b63"; }}
            onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = C.brand; }}
          >
            <FileDown size={14} />
            Export
          </button>
        </div>
      </div>

      {/* ============================================================ */}
      {/* Summary stat strip                                           */}
      {/* ============================================================ */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(4, 1fr)",
        gap: 12,
        marginBottom: 16,
      }}>
        {[
          {
            label: "Total Patients",
            value: totalPatients.toLocaleString(),
            sub: `${stats.analyzedPct}% analyzed`,
            icon: Users,
            tone: C.brand,
          },
          {
            label: "Average RAF",
            value: stats.avgRaf > 0 ? stats.avgRaf.toFixed(3) : "\u2014",
            sub: `${measurementYear} · ${(stats.all - stats.unscored).toLocaleString()} scored`,
            icon: Activity,
            tone: "#0EA5E9",
          },
          {
            label: "High Risk",
            value: stats.high.toLocaleString(),
            sub: `RAF \u2265 2.00`,
            icon: TrendingUp,
            tone: C.high,
          },
          {
            label: "Total HCCs",
            value: stats.hccTotal.toLocaleString(),
            sub: `In current view`,
            icon: ShieldCheck,
            tone: C.low,
          },
        ].map(({ label, value, sub, icon: Icon, tone }) => (
          <div
            key={label}
            style={{
              backgroundColor: C.bgCard,
              border: `1px solid ${C.borderSoft}`,
              borderRadius: 12,
              padding: "14px 16px",
              display: "flex",
              alignItems: "center",
              gap: 14,
              boxShadow: "0 1px 2px rgba(15, 23, 42, 0.03)",
            }}
          >
            <div style={{
              width: 36, height: 36, borderRadius: 10,
              backgroundColor: `${tone}14`,
              color: tone,
              display: "flex", alignItems: "center", justifyContent: "center",
              flexShrink: 0,
            }}>
              <Icon size={17} strokeWidth={2.25} />
            </div>
            <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 2 }}>
              <span style={{
                fontSize: 11, fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                color: C.label,
              }}>
                {label}
              </span>
              <span style={{
                fontSize: 22, fontWeight: 700,
                color: C.text,
                lineHeight: 1.1,
                letterSpacing: "-0.02em",
                fontVariantNumeric: "tabular-nums",
              }}>
                {value}
              </span>
              <span style={{
                fontSize: 11, color: C.textSubtle,
                fontVariantNumeric: "tabular-nums",
              }}>
                {sub}
              </span>
            </div>
          </div>
        ))}
      </div>

      {/* ============================================================ */}
      {/* Filter strip                                                 */}
      {/* ============================================================ */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        flexWrap: "wrap", gap: 12, marginBottom: 14,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          {/* Risk filter as segmented chips */}
          <div style={{
            display: "inline-flex",
            alignItems: "center",
            backgroundColor: "#FFFFFF",
            border: `1px solid ${C.border}`,
            borderRadius: 10,
            padding: 3,
            gap: 2,
            height: 36,
          }}>
            {([
              { key: "all" as const, label: "All", count: stats.all, dot: null },
              { key: "high" as const, label: "High", count: stats.high, dot: C.high },
              { key: "medium" as const, label: "Medium", count: stats.medium, dot: C.medium },
              { key: "low" as const, label: "Low", count: stats.low, dot: C.low },
              { key: "unscored" as const, label: "Unscored", count: stats.unscored, dot: "#CBD5E1" },
            ]).map(({ key, label, count, dot }) => {
              const active = riskFilter === key;
              return (
                <button
                  key={key}
                  onClick={() => { setRiskFilter(key); setPage(0); }}
                  style={{
                    display: "inline-flex", alignItems: "center", gap: 6,
                    height: 28, padding: "0 12px",
                    borderRadius: 7,
                    border: "none",
                    backgroundColor: active ? C.text : "transparent",
                    color: active ? "#FFFFFF" : C.textMuted,
                    fontSize: 12, fontWeight: 600,
                    fontFamily: FONT_SYS,
                    cursor: "pointer",
                    transition: "all 0.15s ease",
                  }}
                >
                  {dot && (
                    <span style={{
                      width: 6, height: 6, borderRadius: 3,
                      backgroundColor: dot,
                      boxShadow: active ? "0 0 0 1.5px rgba(255,255,255,0.25)" : "none",
                    }} />
                  )}
                  {label}
                  <span style={{
                    fontSize: 11, fontWeight: 600,
                    color: active ? "rgba(255,255,255,0.7)" : C.label,
                    fontVariantNumeric: "tabular-nums",
                  }}>
                    {count}
                  </span>
                </button>
              );
            })}
          </div>

          <button
            title={showColumnFilters ? "Hide column filters" : "Show column filters"}
            onClick={() => setShowColumnFilters((v) => !v)}
            style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              height: 36, padding: "0 14px", borderRadius: 10,
              border: `1px solid ${showColumnFilters || hasActiveColFilters ? C.brand : C.border}`,
              backgroundColor: showColumnFilters || hasActiveColFilters ? C.brandSoft : "#FFFFFF",
              color: showColumnFilters || hasActiveColFilters ? C.brand : C.textMuted,
              fontSize: 12, fontWeight: 600,
              fontFamily: FONT_SYS,
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
          >
            <Filter size={13} />
            Column Filters
            {hasActiveColFilters && (
              <span style={{
                minWidth: 18, height: 18, padding: "0 5px", borderRadius: 9,
                backgroundColor: C.brand, color: "#fff",
                fontSize: 10, fontWeight: 700,
                display: "inline-flex", alignItems: "center", justifyContent: "center",
                fontVariantNumeric: "tabular-nums",
              }}>
                {[colFilters.sex !== "all", colFilters.ageMin || colFilters.ageMax, colFilters.rafMin || colFilters.rafMax, colFilters.demoMin || colFilters.demoMax, colFilters.diseaseMin || colFilters.diseaseMax, colFilters.interactMin || colFilters.interactMax, colFilters.hccMin || colFilters.hccMax, colFilters.status !== "all"].filter(Boolean).length}
              </span>
            )}
          </button>
          {hasActiveColFilters && (
            <button
              onClick={() => { clearColFilters(); setPage(0); }}
              style={{
                display: "inline-flex", alignItems: "center", gap: 5,
                height: 36, padding: "0 12px", borderRadius: 10,
                background: "none",
                border: `1px dashed ${C.border}`,
                fontSize: 12, fontWeight: 500,
                color: C.textSubtle, cursor: "pointer",
                fontFamily: FONT_SYS,
              }}
            >
              <FilterX size={12} /> Clear
            </button>
          )}
        </div>

        {!isLoading && (
          <span style={{
            fontSize: 12, color: C.textSubtle, whiteSpace: "nowrap",
            fontVariantNumeric: "tabular-nums",
          }}>
            Showing <strong style={{ color: C.text, fontWeight: 600 }}>{total.toLocaleString()}</strong> of{" "}
            <strong style={{ color: C.text, fontWeight: 600 }}>{totalPatients.toLocaleString()}</strong>
          </span>
        )}
      </div>

      {/* ============================================================ */}
      {/* Worklist                                                     */}
      {/* ============================================================ */}
      <div
        role="table"
        aria-label="Patient worklist"
        aria-rowcount={rows.length}
        aria-busy={isLoading}
        aria-live="polite"
        style={{
          backgroundColor: C.bgCard,
          borderRadius: 14,
          overflow: "hidden",
          border: `1px solid ${C.borderSoft}`,
          boxShadow: "0 1px 2px rgba(15, 23, 42, 0.04), 0 4px 16px rgba(15, 23, 42, 0.04)",
        }}
      >
        {/* ── Group super-header: "Sub-scores" bracket over Demo/Disease/Interact ── */}
        <div style={{
          display: "grid",
          gridTemplateColumns: WORKLIST_GRID,
          alignItems: "end",
          padding: `12px ${WORKLIST_PAD_X}px 0`,
          backgroundColor: "#FCFDFE",
          gap: WORKLIST_GAP,
        }}>
          <span /><span /><span />
          <div style={{
            gridColumn: "4 / span 3",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 10,
            paddingBottom: 6,
          }}>
            <span style={{ flex: 1, height: 1, backgroundColor: C.border }} />
            <span style={{
              fontSize: 9.5, fontWeight: 700,
              textTransform: "uppercase", letterSpacing: "0.14em",
              color: C.label,
              whiteSpace: "nowrap",
            }}>
              Sub-scores
            </span>
            <span style={{ flex: 1, height: 1, backgroundColor: C.border }} />
          </div>
          <span /><span /><span />
        </div>

        {/* Column header */}
        <div role="row" style={{
          display: "grid",
          gridTemplateColumns: WORKLIST_GRID,
          alignItems: "center",
          padding: `8px ${WORKLIST_PAD_X}px 10px`,
          backgroundColor: "#FCFDFE",
          borderBottom: `1px solid ${C.border}`,
          gap: WORKLIST_GAP,
        }}>
          <SortLabel col="name" label="Patient" sort={sort} onSort={handleSort} />
          <SortLabel col="age" label="Age / Sex" sort={sort} onSort={handleSort} />
          <SortLabel col="raf_score" label="RAF Score" sort={sort} onSort={handleSort} />

          <div role="columnheader" title="Demographic RAF — based on age, sex, enrollment status" style={bandCellStyle("left", SUBSCORE_BAND_BG, 30)}>
            <span style={{
              fontSize: 11, fontWeight: 600, textTransform: "uppercase",
              letterSpacing: "0.06em", color: C.label,
            }}>Demo</span>
          </div>
          <div role="columnheader" title="Disease RAF — based on HCC diagnoses and severity" style={bandCellStyle("mid", SUBSCORE_BAND_BG, 30)}>
            <span style={{
              fontSize: 11, fontWeight: 600, textTransform: "uppercase",
              letterSpacing: "0.06em", color: C.label,
            }}>Disease</span>
          </div>
          <div role="columnheader" title="Interaction RAF — HCC disease interaction combinations" style={bandCellStyle("right", SUBSCORE_BAND_BG, 30)}>
            <span style={{
              fontSize: 11, fontWeight: 600, textTransform: "uppercase",
              letterSpacing: "0.06em", color: C.label,
            }}>Interact</span>
          </div>

          <SortLabel col="hcc_count" label="HCCs" sort={sort} onSort={handleSort} align="right" />
          <span role="columnheader" style={{
            fontSize: 11, fontWeight: 600, textTransform: "uppercase",
            letterSpacing: "0.06em", color: C.label,
          }}>Status</span>
          <span role="columnheader" aria-label="Open patient detail" />
        </div>

        {/* ---- Column Filter Row ---- */}
        {showColumnFilters && (
          <div style={{
            display: "grid",
            gridTemplateColumns: WORKLIST_GRID,
            alignItems: "center",
            padding: `10px ${WORKLIST_PAD_X}px`,
            backgroundColor: "#F8FAFC",
            borderBottom: `1px solid ${C.border}`,
            gap: WORKLIST_GAP,
          }}>
            <span style={{ fontSize: 11, color: C.label, fontStyle: "italic" }}>Use search above</span>

            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              <select
                title="Filter by sex"
                value={colFilters.sex}
                onChange={(e) => { setColFilters((f) => ({ ...f, sex: e.target.value as typeof f.sex })); setPage(0); }}
                style={{
                  width: "100%", height: 24, fontSize: 11, borderRadius: 5,
                  border: colFilters.sex !== "all" ? `1px solid ${C.brand}` : `1px solid ${C.border}`,
                  backgroundColor: colFilters.sex !== "all" ? C.brandSoft : "#fff",
                  color: C.textMuted, padding: "0 4px", outline: "none", cursor: "pointer",
                  fontFamily: FONT_SYS,
                }}
              >
                <option value="all">All</option>
                <option value="Male">M</option>
                <option value="Female">F</option>
              </select>
              <div style={{ display: "flex", gap: 2 }}>
                <input
                  title="Minimum age" placeholder="Min"
                  value={colFilters.ageMin}
                  onChange={(e) => { setColFilters((f) => ({ ...f, ageMin: e.target.value })); setPage(0); }}
                  style={{
                    width: "50%", height: 22, fontSize: 11, borderRadius: 4,
                    border: colFilters.ageMin ? `1px solid ${C.brand}` : `1px solid ${C.border}`,
                    padding: "0 4px", outline: "none", textAlign: "center",
                    fontVariantNumeric: "tabular-nums",
                  }}
                  type="number"
                />
                <input
                  title="Maximum age" placeholder="Max"
                  value={colFilters.ageMax}
                  onChange={(e) => { setColFilters((f) => ({ ...f, ageMax: e.target.value })); setPage(0); }}
                  style={{
                    width: "50%", height: 22, fontSize: 11, borderRadius: 4,
                    border: colFilters.ageMax ? `1px solid ${C.brand}` : `1px solid ${C.border}`,
                    padding: "0 4px", outline: "none", textAlign: "center",
                    fontVariantNumeric: "tabular-nums",
                  }}
                  type="number"
                />
              </div>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <input
                title="Minimum RAF score" placeholder="Min"
                value={colFilters.rafMin}
                onChange={(e) => { setColFilters((f) => ({ ...f, rafMin: e.target.value })); setPage(0); }}
                style={{
                  width: "100%", height: 22, fontSize: 11, borderRadius: 4,
                  border: colFilters.rafMin ? `1px solid ${C.brand}` : `1px solid ${C.border}`,
                  padding: "0 4px", outline: "none", textAlign: "center",
                  fontVariantNumeric: "tabular-nums",
                }}
                type="number" step="0.1"
              />
              <input
                title="Maximum RAF score" placeholder="Max"
                value={colFilters.rafMax}
                onChange={(e) => { setColFilters((f) => ({ ...f, rafMax: e.target.value })); setPage(0); }}
                style={{
                  width: "100%", height: 22, fontSize: 11, borderRadius: 4,
                  border: colFilters.rafMax ? `1px solid ${C.brand}` : `1px solid ${C.border}`,
                  padding: "0 4px", outline: "none", textAlign: "center",
                  fontVariantNumeric: "tabular-nums",
                }}
                type="number" step="0.1"
              />
            </div>

            <div style={bandCellStyle("left", SUBSCORE_BAND_BG, 50)}>
              <div style={{ display: "flex", flexDirection: "column", gap: 2, width: "100%" }}>
                <input title="Min demographic score" placeholder="Min" value={colFilters.demoMin} onChange={(e) => { setColFilters((f) => ({ ...f, demoMin: e.target.value })); setPage(0); }} type="number" step="0.01" style={{ width: "100%", height: 20, fontSize: 10, borderRadius: 4, border: colFilters.demoMin ? `1px solid ${C.brand}` : `1px solid ${C.border}`, padding: "0 4px", outline: "none", textAlign: "center", fontVariantNumeric: "tabular-nums" }} />
                <input title="Max demographic score" placeholder="Max" value={colFilters.demoMax} onChange={(e) => { setColFilters((f) => ({ ...f, demoMax: e.target.value })); setPage(0); }} type="number" step="0.01" style={{ width: "100%", height: 20, fontSize: 10, borderRadius: 4, border: colFilters.demoMax ? `1px solid ${C.brand}` : `1px solid ${C.border}`, padding: "0 4px", outline: "none", textAlign: "center", fontVariantNumeric: "tabular-nums" }} />
              </div>
            </div>

            <div style={bandCellStyle("mid", SUBSCORE_BAND_BG, 50)}>
              <div style={{ display: "flex", flexDirection: "column", gap: 2, width: "100%" }}>
                <input title="Min disease score" placeholder="Min" value={colFilters.diseaseMin} onChange={(e) => { setColFilters((f) => ({ ...f, diseaseMin: e.target.value })); setPage(0); }} type="number" step="0.01" style={{ width: "100%", height: 20, fontSize: 10, borderRadius: 4, border: colFilters.diseaseMin ? `1px solid ${C.brand}` : `1px solid ${C.border}`, padding: "0 4px", outline: "none", textAlign: "center", fontVariantNumeric: "tabular-nums" }} />
                <input title="Max disease score" placeholder="Max" value={colFilters.diseaseMax} onChange={(e) => { setColFilters((f) => ({ ...f, diseaseMax: e.target.value })); setPage(0); }} type="number" step="0.01" style={{ width: "100%", height: 20, fontSize: 10, borderRadius: 4, border: colFilters.diseaseMax ? `1px solid ${C.brand}` : `1px solid ${C.border}`, padding: "0 4px", outline: "none", textAlign: "center", fontVariantNumeric: "tabular-nums" }} />
              </div>
            </div>

            <div style={bandCellStyle("right", SUBSCORE_BAND_BG, 50)}>
              <div style={{ display: "flex", flexDirection: "column", gap: 2, width: "100%" }}>
                <input title="Min interaction score" placeholder="Min" value={colFilters.interactMin} onChange={(e) => { setColFilters((f) => ({ ...f, interactMin: e.target.value })); setPage(0); }} type="number" step="0.01" style={{ width: "100%", height: 20, fontSize: 10, borderRadius: 4, border: colFilters.interactMin ? `1px solid ${C.brand}` : `1px solid ${C.border}`, padding: "0 4px", outline: "none", textAlign: "center", fontVariantNumeric: "tabular-nums" }} />
                <input title="Max interaction score" placeholder="Max" value={colFilters.interactMax} onChange={(e) => { setColFilters((f) => ({ ...f, interactMax: e.target.value })); setPage(0); }} type="number" step="0.01" style={{ width: "100%", height: 20, fontSize: 10, borderRadius: 4, border: colFilters.interactMax ? `1px solid ${C.brand}` : `1px solid ${C.border}`, padding: "0 4px", outline: "none", textAlign: "center", fontVariantNumeric: "tabular-nums" }} />
              </div>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <input
                title="Minimum HCC count" placeholder="Min"
                value={colFilters.hccMin}
                onChange={(e) => { setColFilters((f) => ({ ...f, hccMin: e.target.value })); setPage(0); }}
                style={{
                  width: "100%", height: 22, fontSize: 11, borderRadius: 4,
                  border: colFilters.hccMin ? `1px solid ${C.brand}` : `1px solid ${C.border}`,
                  padding: "0 4px", outline: "none", textAlign: "center",
                  fontVariantNumeric: "tabular-nums",
                }}
                type="number"
              />
              <input
                title="Maximum HCC count" placeholder="Max"
                value={colFilters.hccMax}
                onChange={(e) => { setColFilters((f) => ({ ...f, hccMax: e.target.value })); setPage(0); }}
                style={{
                  width: "100%", height: 22, fontSize: 11, borderRadius: 4,
                  border: colFilters.hccMax ? `1px solid ${C.brand}` : `1px solid ${C.border}`,
                  padding: "0 4px", outline: "none", textAlign: "center",
                  fontVariantNumeric: "tabular-nums",
                }}
                type="number"
              />
            </div>

            <select
              title="Filter by analysis status"
              value={colFilters.status}
              onChange={(e) => { setColFilters((f) => ({ ...f, status: e.target.value as typeof f.status })); setPage(0); }}
              style={{
                width: "100%", height: 24, fontSize: 11, borderRadius: 5,
                border: colFilters.status !== "all" ? `1px solid ${C.brand}` : `1px solid ${C.border}`,
                backgroundColor: colFilters.status !== "all" ? C.brandSoft : "#fff",
                color: C.textMuted, padding: "0 4px", outline: "none", cursor: "pointer",
                fontFamily: FONT_SYS,
              }}
            >
              <option value="all">All</option>
              <option value="analyzed">Analyzed</option>
              <option value="pending">Pending</option>
            </select>

            <span />
          </div>
        )}

        {/* ---- Loading Skeleton ---- */}
        {isLoading && Array.from({ length: 8 }).map((_, i) => (
          <div
            key={i}
            aria-hidden="true"
            style={{
              display: "grid",
              gridTemplateColumns: WORKLIST_GRID,
              alignItems: "center",
              padding: `0 ${WORKLIST_PAD_X}px 0 ${WORKLIST_PAD_X - 3}px`,
              height: ROW_HEIGHT,
              borderBottom: `1px solid ${C.rowDivider}`,
              borderLeft: `3px solid ${C.borderSoft}`,
              gap: WORKLIST_GAP,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div style={{ width: 40, height: 40, borderRadius: 12, backgroundColor: "#F1F5F9", animation: "pulse 1.5s ease-in-out infinite" }} />
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <div style={{ width: 140, height: 12, borderRadius: 4, backgroundColor: "#F1F5F9", animation: "pulse 1.5s ease-in-out infinite" }} />
                <div style={{ width: 60, height: 10, borderRadius: 4, backgroundColor: "#F1F5F9", animation: "pulse 1.5s ease-in-out infinite" }} />
              </div>
            </div>
            <div style={{ width: 36, height: 12, borderRadius: 4, backgroundColor: "#F1F5F9", animation: "pulse 1.5s ease-in-out infinite" }} />
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <div style={{ width: 56, height: 18, borderRadius: 4, backgroundColor: "#F1F5F9", animation: "pulse 1.5s ease-in-out infinite" }} />
              <div style={{ width: 44, height: 10, borderRadius: 4, backgroundColor: "#F1F5F9", animation: "pulse 1.5s ease-in-out infinite" }} />
            </div>
            <div style={bandCellStyle("left")}>
              <div style={{ width: 38, height: 11, borderRadius: 4, backgroundColor: "#E2E8F0", animation: "pulse 1.5s ease-in-out infinite" }} />
            </div>
            <div style={bandCellStyle("mid")}>
              <div style={{ width: 38, height: 11, borderRadius: 4, backgroundColor: "#E2E8F0", animation: "pulse 1.5s ease-in-out infinite" }} />
            </div>
            <div style={bandCellStyle("right")}>
              <div style={{ width: 38, height: 11, borderRadius: 4, backgroundColor: "#E2E8F0", animation: "pulse 1.5s ease-in-out infinite" }} />
            </div>
            <div style={{ width: 32, height: 18, borderRadius: 4, backgroundColor: "#F1F5F9", animation: "pulse 1.5s ease-in-out infinite", justifySelf: "end" }} />
            <div style={{ width: 86, height: 22, borderRadius: 999, backgroundColor: "#F1F5F9", animation: "pulse 1.5s ease-in-out infinite" }} />
            <div />
          </div>
        ))}

        {/* ---- Empty State ---- */}
        {!isLoading && rows.length === 0 && (
          <div style={{ padding: "72px 24px", textAlign: "center" }}>
            <div style={{
              width: 72, height: 72, borderRadius: 18, margin: "0 auto 18px",
              background: "linear-gradient(135deg, #F8FAFC 0%, #F1F5F9 100%)",
              display: "flex", alignItems: "center", justifyContent: "center",
              border: `1px dashed ${C.border}`,
            }}>
              <Users size={28} color={C.label} strokeWidth={1.75} />
            </div>
            <h3 style={{
              fontSize: 16, fontWeight: 600, color: C.text,
              margin: "0 0 6px",
              letterSpacing: "-0.01em",
            }}>
              No patients match your criteria
            </h3>
            <p style={{
              fontSize: 13, color: C.textSubtle,
              margin: "0 auto 18px", maxWidth: 320,
            }}>
              Try broadening your search or adjusting the risk filter to see more results.
            </p>
            {(riskFilter !== "all" || debouncedSearch || hasActiveColFilters) && (
              <button
                onClick={() => { setRiskFilter("all"); setSearch(""); clearColFilters(); setPage(0); }}
                style={{
                  padding: "8px 18px", borderRadius: 10,
                  border: `1px solid ${C.border}`,
                  backgroundColor: "#FFFFFF",
                  color: C.brand,
                  fontSize: 13, fontWeight: 600, cursor: "pointer",
                  fontFamily: FONT_SYS,
                  transition: "all 0.15s ease",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.borderColor = C.brand; e.currentTarget.style.backgroundColor = C.brandSoft; }}
                onMouseLeave={(e) => { e.currentTarget.style.borderColor = C.border; e.currentTarget.style.backgroundColor = "#FFFFFF"; }}
              >
                Clear all filters
              </button>
            )}
          </div>
        )}

        {/* ---- Patient Rows ---- */}
        {rows.map((p, rowIndex) => {
          const pid = p.pid;
          const age = p.DOB ? calculateAge(p.DOB) : null;
          const score = p.raf_score ?? 0;
          const hccCount = p.hcc_count ?? 0;
          const scored = score > 0;
          const fullName = `${p.lname || ""}, ${p.fname || ""}`.trim().replace(/^,\s*/, "").replace(/,\s*$/, "") || "\u2022";
          const initials = deriveInitials(p.fname, p.lname, pid);
          const sexLabel =
            p.sex === "Female" ? "F" :
            p.sex === "Male" ? "M" :
            p.sex ? p.sex[0] : "\u2014";
          const avatarColor = initialsColor(fullName);
          const isHovered = hoveredRow === pid;
          const accent = riskAccentColor(scored ? score : null);
          const tone = riskTone(scored ? score : null);

          const rowBandBg = isHovered ? C.bgBandHover : SUBSCORE_BAND_BG;

          return (
            <div
              key={p.pid}
              role="row"
              tabIndex={0}
              aria-label={`${fullName}, ${age !== null ? `age ${age}` : "age unknown"}, RAF ${scored ? Number(score).toFixed(2) : "not calculated"}, ${tone.label} risk, ${hccCount} HCC${hccCount === 1 ? "" : "s"}`}
              onClick={() => router.push(`/patients/${pid}`)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  router.push(`/patients/${pid}`);
                }
              }}
              onMouseEnter={() => setHoveredRow(pid)}
              onMouseLeave={() => setHoveredRow(null)}
              style={{
                display: "grid",
                gridTemplateColumns: WORKLIST_GRID,
                alignItems: "center",
                height: ROW_HEIGHT,
                padding: `0 ${WORKLIST_PAD_X}px 0 ${WORKLIST_PAD_X - 3}px`,
                borderBottom: `1px solid ${C.rowDivider}`,
                borderLeft: `3px solid ${accent}`,
                backgroundColor: isHovered ? "#FAFBFC" : C.bgCard,
                cursor: "pointer",
                transition: "background-color 0.15s ease",
                gap: WORKLIST_GAP,
                outline: "none",
                animation: `fadeSlideIn 0.25s ease-out ${Math.min(rowIndex, 12) * 0.025}s both`,
              }}
              onFocus={(e) => { e.currentTarget.style.boxShadow = `inset 0 0 0 2px ${C.brandSoft}`; }}
              onBlur={(e) => { e.currentTarget.style.boxShadow = "none"; }}
            >
              {/* Patient: avatar + name + caption */}
              <div title={`${fullName} · PID ${pid}`} style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
                <div style={{
                  width: 40, height: 40, borderRadius: 11, flexShrink: 0,
                  background: `linear-gradient(135deg, ${avatarColor}1F 0%, ${avatarColor}0F 100%)`,
                  color: avatarColor,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 13, fontWeight: 700,
                  letterSpacing: "0.02em",
                  border: `1px solid ${avatarColor}26`,
                  boxShadow: "inset 0 1px 0 rgba(255,255,255,0.7)",
                }}>
                  {initials}
                </div>
                <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 2 }}>
                  <span style={{
                    fontSize: 14, fontWeight: 600, color: C.text,
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                    letterSpacing: "-0.005em",
                    lineHeight: 1.2,
                  }}>
                    {fullName}
                  </span>
                  <span style={{
                    fontSize: 11,
                    color: C.label,
                    fontFamily: FONT_MONO,
                    fontVariantNumeric: "tabular-nums",
                    whiteSpace: "nowrap",
                    letterSpacing: "0.02em",
                  }}>
                    PID {pid}
                    {age !== null && (
                      <>
                        <span style={{ margin: "0 6px", color: "#CBD5E1" }}>·</span>
                        {age}{sexLabel !== "\u2014" ? ` ${sexLabel}` : ""}
                      </>
                    )}
                    {(p as unknown as Record<string, unknown>).data_source === "upload" && (
                      <>
                        <span style={{ margin: "0 6px", color: "#CBD5E1" }}>·</span>
                        <span style={{
                          fontSize: 9, fontWeight: 600, letterSpacing: "0.04em",
                          padding: "1px 5px", borderRadius: 4,
                          background: "#EFF6FF", color: "#3B82F6", border: "1px solid #BFDBFE",
                          textTransform: "uppercase",
                        }}>CSV</span>
                      </>
                    )}
                  </span>
                </div>
              </div>

              {/* Age / Sex */}
              <span
                title={`Age: ${age ?? "Unknown"} · Sex: ${p.sex ?? "Unknown"} · DOB: ${p.DOB ?? "N/A"}`}
                style={{
                  fontSize: 13, color: C.textMuted,
                  fontVariantNumeric: "tabular-nums",
                  fontWeight: 500,
                }}
              >
                {age !== null ? `${age} ${sexLabel}` : sexLabel}
              </span>

              {/* RAF Score — hero */}
              <div
                title={`Total CMS-HCC RAF Score: ${scored ? Number(score).toFixed(4) : "Not yet calculated"}`}
                style={{ minWidth: 0 }}
              >
                {scored ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "flex-start" }}>
                    <span style={{
                      fontSize: 22,
                      fontWeight: 700,
                      color: C.text,
                      fontFamily: FONT_SYS,
                      fontVariantNumeric: "tabular-nums",
                      lineHeight: 1,
                      letterSpacing: "-0.025em",
                    }}>
                      {Number(score).toFixed(2)}
                    </span>
                    <span
                      aria-label={`${tone.label} risk`}
                      style={{
                        display: "inline-flex", alignItems: "center",
                        height: 16, padding: "0 6px",
                        borderRadius: 4,
                        backgroundColor: tone.bg,
                        color: tone.fg,
                        fontSize: 9.5, fontWeight: 700,
                        textTransform: "uppercase",
                        letterSpacing: "0.06em",
                        lineHeight: 1,
                      }}
                    >
                      {tone.label}
                    </span>
                  </div>
                ) : (
                  <span style={{
                    fontSize: 20, color: "#CBD5E1", fontWeight: 400,
                    fontFamily: FONT_SYS,
                    fontVariantNumeric: "tabular-nums",
                  }}>{"\u2014"}</span>
                )}
              </div>

              {/* Demographic — sub-score band left */}
              <div
                title={`Demographic Score: ${p.demographic_score != null ? Number(p.demographic_score).toFixed(4) : "N/A"}`}
                style={bandCellStyle("left", rowBandBg)}
              >
                {p.demographic_score != null ? (
                  <span style={{
                    fontSize: 13, fontWeight: 500, color: C.textMuted,
                    fontFamily: FONT_SYS,
                    fontVariantNumeric: "tabular-nums",
                    letterSpacing: "-0.005em",
                  }}>
                    {Number(p.demographic_score).toFixed(3)}
                  </span>
                ) : (
                  <span style={{ fontSize: 13, color: "#CBD5E1", fontWeight: 400 }}>{"\u2014"}</span>
                )}
              </div>

              {/* Disease — sub-score band mid */}
              <div
                title={`Disease Score: ${p.disease_score != null ? Number(p.disease_score).toFixed(4) : "N/A"}`}
                style={bandCellStyle("mid", rowBandBg)}
              >
                {p.disease_score != null ? (
                  <span style={{
                    fontSize: 13, fontWeight: 500, color: C.textMuted,
                    fontFamily: FONT_SYS,
                    fontVariantNumeric: "tabular-nums",
                    letterSpacing: "-0.005em",
                  }}>
                    {Number(p.disease_score).toFixed(3)}
                  </span>
                ) : (
                  <span style={{ fontSize: 13, color: "#CBD5E1", fontWeight: 400 }}>{"\u2014"}</span>
                )}
              </div>

              {/* Interaction — sub-score band right */}
              <div
                title={`Interaction Score: ${p.interaction_score != null ? Number(p.interaction_score).toFixed(4) : "N/A"}`}
                style={bandCellStyle("right", rowBandBg)}
              >
                {p.interaction_score != null ? (
                  <span style={{
                    fontSize: 13, fontWeight: 500, color: C.textMuted,
                    fontFamily: FONT_SYS,
                    fontVariantNumeric: "tabular-nums",
                    letterSpacing: "-0.005em",
                  }}>
                    {Number(p.interaction_score).toFixed(3)}
                  </span>
                ) : (
                  <span style={{ fontSize: 13, color: "#CBD5E1", fontWeight: 400 }}>{"\u2014"}</span>
                )}
              </div>

              {/* HCC Count */}
              <div
                title={`${hccCount} Hierarchical Condition Categories identified`}
                style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 1 }}
              >
                {hccCount > 0 ? (
                  <>
                    <span style={{
                      fontSize: 18, fontWeight: 700, color: C.text,
                      fontFamily: FONT_SYS,
                      fontVariantNumeric: "tabular-nums",
                      lineHeight: 1,
                      letterSpacing: "-0.015em",
                    }}>
                      {hccCount}
                    </span>
                    <span style={{
                      fontSize: 9, fontWeight: 600,
                      color: C.label,
                      textTransform: "uppercase",
                      letterSpacing: "0.08em",
                    }}>
                      {hccCount === 1 ? "HCC" : "HCCs"}
                    </span>
                  </>
                ) : (
                  <span style={{ fontSize: 17, color: "#CBD5E1", fontWeight: 400 }}>{"\u2014"}</span>
                )}
              </div>

              {/* Status pill */}
              <div title={scored ? "RAF score has been calculated" : "RAF score pending — patient needs analysis"}>
                <span style={{
                  display: "inline-flex", alignItems: "center", gap: 6,
                  height: 22, padding: "0 10px 0 8px",
                  borderRadius: 999,
                  backgroundColor: scored ? C.lowSoft : "#F8FAFC",
                  border: `1px solid ${scored ? "#BBF7D0" : C.border}`,
                  fontSize: 11, fontWeight: 600,
                  color: scored ? "#047857" : C.label,
                  whiteSpace: "nowrap",
                  letterSpacing: "-0.005em",
                }}>
                  <span style={{
                    width: 6, height: 6, borderRadius: 3,
                    backgroundColor: scored ? "#10B981" : "#CBD5E1",
                    boxShadow: scored ? "0 0 0 2px rgba(16,185,129,0.18)" : "none",
                  }} />
                  {scored ? "Analyzed" : "Pending"}
                </span>
              </div>

              {/* Chevron */}
              <ChevronRight
                size={16}
                color={isHovered ? C.brand : "#CBD5E1"}
                style={{
                  transform: isHovered ? "translateX(2px)" : "translateX(0)",
                  transition: "transform 0.15s ease, color 0.15s ease",
                }}
              />
            </div>
          );
        })}

        {/* ---- Pagination ---- */}
        {!isLoading && totalPages > 1 && (
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            gap: 8, padding: "14px 20px",
            borderTop: `1px solid ${C.border}`,
            backgroundColor: "#FCFDFE",
          }}>
            <span style={{
              fontSize: 12, color: C.textSubtle,
              fontVariantNumeric: "tabular-nums",
            }}>
              Page <strong style={{ color: C.text, fontWeight: 600 }}>{page + 1}</strong> of{" "}
              <strong style={{ color: C.text, fontWeight: 600 }}>{totalPages}</strong>
            </span>

            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <button
                disabled={page === 0}
                onClick={() => setPage((p) => p - 1)}
                style={{
                  display: "inline-flex", alignItems: "center", gap: 4,
                  height: 32, padding: "0 12px", borderRadius: 8,
                  border: `1px solid ${C.border}`, backgroundColor: "#FFFFFF",
                  fontSize: 12, fontWeight: 500,
                  color: page === 0 ? "#CBD5E1" : C.textMuted,
                  cursor: page === 0 ? "not-allowed" : "pointer",
                  opacity: page === 0 ? 0.6 : 1,
                  fontFamily: FONT_SYS,
                  transition: "all 0.15s ease",
                }}
                aria-label="Previous page"
              >
                <ChevronLeft size={13} /> Prev
              </button>

              {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
                let pageNum: number;
                if (totalPages <= 7) {
                  pageNum = i;
                } else if (page < 3) {
                  pageNum = i;
                } else if (page > totalPages - 4) {
                  pageNum = totalPages - 7 + i;
                } else {
                  pageNum = page - 3 + i;
                }
                const isActive = pageNum === page;
                return (
                  <button
                    key={pageNum}
                    onClick={() => setPage(pageNum)}
                    style={{
                      width: 32, height: 32, borderRadius: 8,
                      display: "inline-flex", alignItems: "center", justifyContent: "center",
                      border: isActive ? "none" : `1px solid transparent`,
                      backgroundColor: isActive ? C.brand : "transparent",
                      color: isActive ? "#FFFFFF" : C.textSubtle,
                      fontSize: 12, fontWeight: isActive ? 600 : 500,
                      fontFamily: FONT_SYS,
                      fontVariantNumeric: "tabular-nums",
                      cursor: "pointer",
                      transition: "all 0.15s ease",
                      boxShadow: isActive ? "0 2px 6px rgba(15, 118, 110, 0.25)" : "none",
                    }}
                    onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.backgroundColor = "#F1F5F9"; }}
                    onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.backgroundColor = "transparent"; }}
                  >
                    {pageNum + 1}
                  </button>
                );
              })}

              <button
                disabled={page >= totalPages - 1}
                onClick={() => setPage((p) => p + 1)}
                style={{
                  display: "inline-flex", alignItems: "center", gap: 4,
                  height: 32, padding: "0 12px", borderRadius: 8,
                  border: `1px solid ${C.border}`, backgroundColor: "#FFFFFF",
                  fontSize: 12, fontWeight: 500,
                  color: page >= totalPages - 1 ? "#CBD5E1" : C.textMuted,
                  cursor: page >= totalPages - 1 ? "not-allowed" : "pointer",
                  opacity: page >= totalPages - 1 ? 0.6 : 1,
                  fontFamily: FONT_SYS,
                  transition: "all 0.15s ease",
                }}
                aria-label="Next page"
              >
                Next <ChevronRight size={13} />
              </button>
            </div>
          </div>
        )}
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes fadeSlideIn {
          from { opacity: 0; transform: translateY(6px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      `}</style>

      {showImportModal && (
        <ImportCSVModal
          onClose={() => setShowImportModal(false)}
          onImported={() => refetch()}
        />
      )}
    </div>
    </ErrorBoundary>
  );
}
