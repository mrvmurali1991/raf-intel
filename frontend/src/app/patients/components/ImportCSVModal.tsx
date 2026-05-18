"use client";

import { useState, useRef } from "react";
import { FocusTrap } from "@/components/ui/focus-trap";
import api from "@/lib/api";
import { tokens } from "@/styles/tokens";
import {
  X,
  Upload,
  CheckCircle,
  Download,
  ShieldCheck,
  RefreshCw,
  Trash2,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
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

export interface ImportCSVModalProps {
  onClose: () => void;
  onImported: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ImportCSVModal({ onClose, onImported }: ImportCSVModalProps) {
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
    const rows = lines.slice(1, 6).map((l) => l.split(",").map((v) => v.trim()));
    setPreview(rows);
  }

  function parseFhirPreview(text: string) {
    try {
      const json = JSON.parse(text);
      let count = 0;
      if (json.resourceType === "Bundle" && Array.isArray(json.entry)) {
        count = json.entry.filter(
          (e: { resource?: { resourceType?: string } }) =>
            e?.resource?.resourceType === "Patient",
        ).length;
      } else if (json.resourceType === "Patient") {
        count = 1;
      }
      setFhirResourceCount(count);
    } catch {
      setUploadError(
        "Could not parse JSON. Please upload a valid FHIR R4 Patient resource or Bundle.",
      );
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
    const endpoint =
      format === "csv"
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
      const detail = (
        err as {
          response?: {
            data?: {
              detail?: string | { message?: string; errors?: string[] };
            };
          };
        }
      )?.response?.data?.detail;
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
        const cols =
          "first_name,middle_name,last_name,previous_name,dob,sex,birth_sex,gender_identity,sexual_orientation,pronouns,ssn,phone,email,address,city,state,zip,race,ethnicity,preferred_language,mrn,mbi,insurance_type,emergency_contact_name,emergency_contact_phone";
        const example =
          "Jane,Marie,Doe,,1980-04-15,Female,Female,Woman,Straight or Heterosexual,she/her,,,jane.doe@example.com,123 Main St,Springfield,IL,62701,White,Not Hispanic or Latino,English,MRN00001,,Medicare,,";
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
        const url = URL.createObjectURL(
          new Blob([response.data], { type: "application/json" }),
        );
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
                  {
                    line: ["123 Main St"],
                    city: "Springfield",
                    state: "IL",
                    postalCode: "62701",
                  },
                ],
                identifier: [
                  {
                    system: "http://terminology.hl7.org/CodeSystem/v2-0203",
                    type: { coding: [{ code: "MR" }] },
                    value: "MRN00001",
                  },
                ],
              },
            },
          ],
        };
        const blob = new Blob([JSON.stringify(template, null, 2)], {
          type: "application/json",
        });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "patient_import_template_fhir.json";
        a.click();
        URL.revokeObjectURL(url);
      }
    }
  }

  return (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center p-6 bg-slate-900/55"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
      role="presentation"
    >
      <FocusTrap>
        <div
          className="bg-white rounded-xl p-8 w-full max-w-[640px] max-h-[90vh] overflow-y-auto shadow-[0_25px_60px_rgba(15,23,42,0.25)] flex flex-col gap-5"
          role="dialog"
          aria-modal="true"
          aria-labelledby="import-modal-title"
        >
          <div className="flex items-start justify-between">
            <div>
              <h2 id="import-modal-title" className="m-0 text-xl font-bold text-slate-900">
                Import Patients
              </h2>
              <p className="mt-1 mb-0 text-sm text-slate-500">
                {format === "csv"
                  ? "Upload a CSV file to bulk-import patients into OpenEMR."
                  : "Upload a FHIR R4 Patient resource or Bundle to import patients."}
              </p>
            </div>
            <button
              onClick={onClose}
              aria-label="Close"
              className="bg-transparent border-none p-2.5 cursor-pointer text-slate-400 rounded-lg w-11 h-11 inline-flex items-center justify-center shrink-0"
            >
              <X size={20} />
            </button>
          </div>

          {/* Format switcher */}
          <div className="inline-flex items-center bg-slate-100 rounded-[10px] p-1 gap-0.5 self-start">
            {(["csv", "fhir"] as const).map((f) => (
              <button
                key={f}
                onClick={() => handleFormatSwitch(f)}
                style={{
                  padding: "5px 18px",
                  borderRadius: 7,
                  border: "none",
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: "pointer",
                  transition: "all 0.15s ease",
                  backgroundColor: format === f ? tokens.teal700 : "transparent",
                  color: format === f ? tokens.white : tokens.slate500,
                  boxShadow: format === f ? "0 2px 6px rgba(15,118,110,0.25)" : "none",
                }}
                aria-pressed={format === f}
              >
                {f === "csv" ? "CSV" : "FHIR JSON"}
              </button>
            ))}
          </div>

          {/* Template download */}
          <div className="flex items-center gap-2">
            <button
              onClick={handleDownloadTemplate}
              className="inline-flex items-center gap-1.5 py-[7px] px-3.5 rounded-lg border border-teal-700/30 bg-teal-700/[0.06] text-teal-700 text-[13px] font-semibold cursor-pointer"
            >
              <Download size={14} />{" "}
              {format === "csv" ? "Download Template" : "Download FHIR Template"}
            </button>
            {format === "csv" && (
              <button
                onClick={async () => {
                  try {
                    const response = await api.get("/api/patients/import/template/excel", {
                      responseType: "arraybuffer",
                    });
                    const url = URL.createObjectURL(
                      new Blob([response.data], {
                        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                      }),
                    );
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = "patient_import_template.xlsx";
                    a.click();
                    URL.revokeObjectURL(url);
                  } catch {
                    alert("Failed to download Excel template.");
                  }
                }}
                className="inline-flex items-center gap-1.5 py-[7px] px-3.5 rounded-lg border border-teal-700/30 bg-teal-700/[0.06] text-teal-700 text-[13px] font-semibold cursor-pointer"
              >
                <Download size={14} /> Download Excel Template
              </button>
            )}
            <span className="text-xs text-slate-400">
              {format === "csv"
                ? "Required columns: first_name, last_name, dob, sex (CSV or Excel)"
                : "FHIR R4 Patient resource or Bundle"}
            </span>
          </div>

          {/* Drop zone */}
          {!result && (
            <div
              role="button"
              tabIndex={0}
              aria-label="Click or drag to upload patient CSV"
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  fileInputRef.current?.click();
                }
              }}
              style={{
                border: `2px dashed ${dragOver ? tokens.teal700 : file ? tokens.success : tokens.slate300}`,
                borderRadius: 14,
                padding: "32px 24px",
                textAlign: "center",
                cursor: "pointer",
                backgroundColor: dragOver
                  ? tokens.tealSoft
                  : file
                    ? "rgba(16, 185, 129, 0.04)"
                    : tokens.slate50,
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
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  gap: 10,
                }}
              >
                <div
                  style={{
                    width: 48,
                    height: 48,
                    borderRadius: 10,
                    backgroundColor: file
                      ? "rgba(16, 185, 129, 0.12)"
                      : "rgba(15, 118, 110, 0.1)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  {file ? (
                    <CheckCircle size={24} color={tokens.success} />
                  ) : (
                    <Upload size={24} color={tokens.teal700} />
                  )}
                </div>
                {file ? (
                  <>
                    <p className="m-0 text-sm font-semibold text-slate-900">{file.name}</p>
                    <p className="m-0 text-xs text-slate-500">
                      {(file.size / 1024).toFixed(1)} KB — click to change
                    </p>
                  </>
                ) : (
                  <>
                    <p className="m-0 text-sm font-semibold text-slate-900">
                      {format === "csv"
                        ? "Drop a CSV or Excel file here or click to browse"
                        : "Drop a FHIR JSON file here or click to browse"}
                    </p>
                    <p className="m-0 text-xs text-slate-400">
                      {format === "csv"
                        ? "Accepts .csv and .xlsx files up to 10 MB"
                        : "Accepts .json files up to 10 MB"}
                    </p>
                  </>
                )}
              </div>
            </div>
          )}

          {/* Duplicate strategy */}
          {file && !result && (
            <div>
              <p className="mt-0 mb-2.5 text-[13px] font-semibold text-slate-600">
                If a patient already exists in the system:
              </p>
              <div style={{ display: "flex", gap: 10 }}>
                {(
                  [
                    {
                      key: "skip" as const,
                      icon: ShieldCheck,
                      label: "Skip existing",
                      desc: "Keep existing patient records unchanged. Only new patients are imported.",
                    },
                    {
                      key: "update" as const,
                      icon: RefreshCw,
                      label: "Update existing",
                      desc: "Update existing patients with new data from your file. New patients are also added.",
                    },
                    {
                      key: "replace" as const,
                      icon: Trash2,
                      label: "Replace all",
                      desc: "Remove all existing patients and import only the patients from your file.",
                    },
                  ] as {
                    key: "skip" | "update" | "replace";
                    icon: React.ElementType;
                    label: string;
                    desc: string;
                  }[]
                ).map(({ key, icon: Icon, label, desc }) => (
                  <button
                    key={key}
                    onClick={() => setOnDuplicate(key)}
                    style={{
                      flex: 1,
                      padding: "14px 16px",
                      borderRadius: 10,
                      border: `2px solid ${
                        onDuplicate === key
                          ? key === "replace"
                            ? tokens.dangerStrong
                            : tokens.teal700
                          : tokens.slate200
                      }`,
                      backgroundColor:
                        onDuplicate === key
                          ? key === "replace"
                            ? "rgba(220, 38, 38, 0.05)"
                            : tokens.tealSoft
                          : tokens.white,
                      cursor: "pointer",
                      textAlign: "left",
                      transition: "border-color 0.15s, background-color 0.15s",
                    }}
                  >
                    <div
                      style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}
                    >
                      <Icon
                        size={16}
                        color={
                          onDuplicate === key
                            ? key === "replace"
                              ? tokens.dangerStrong
                              : tokens.teal700
                            : tokens.slate400
                        }
                      />
                      <span
                        style={{
                          fontSize: 13,
                          fontWeight: 700,
                          color:
                            onDuplicate === key
                              ? key === "replace"
                                ? tokens.dangerStrong
                                : tokens.teal700
                              : tokens.slate900,
                        }}
                      >
                        {label}
                      </span>
                    </div>
                    <p className="m-0 text-xs text-slate-500 leading-[1.4]">{desc}</p>
                  </button>
                ))}
              </div>
              {onDuplicate === "replace" && (
                <div
                  style={{
                    marginTop: 8,
                    padding: "8px 12px",
                    borderRadius: 8,
                    backgroundColor: "rgba(220, 38, 38, 0.08)",
                    border: `1px solid ${tokens.dangerBorder}`,
                  }}
                >
                  <p style={{ margin: 0, fontSize: 12, color: tokens.dangerStrong, fontWeight: 600 }}>
                    Warning: This will permanently delete all existing patients before importing.
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Error */}
          {uploadError && (
            <div
              style={{
                padding: "12px 16px",
                borderRadius: 10,
                backgroundColor: tokens.dangerSoft,
                border: `1px solid ${tokens.dangerBorder}`,
                color: tokens.dangerAlt,
                fontSize: 13,
              }}
            >
              <strong>Error: </strong>
              {uploadError}
            </div>
          )}

          {/* Excel preview indicator */}
          {file && format === "csv" && file.name.toLowerCase().endsWith(".xlsx") && !result && (
            <div
              style={{
                padding: "14px 18px",
                borderRadius: 10,
                backgroundColor: "rgba(15, 118, 110, 0.06)",
                border: "1px solid rgba(15, 118, 110, 0.25)",
                display: "flex",
                alignItems: "center",
                gap: 10,
              }}
            >
              <CheckCircle size={18} color={tokens.teal700} />
              <span style={{ fontSize: 14, fontWeight: 600, color: tokens.teal700 }}>
                Excel file selected: {file.name} ({(file.size / 1024).toFixed(1)} KB)
              </span>
            </div>
          )}

          {/* CSV preview */}
          {file && format === "csv" && headers.length > 0 && !result && (
            <div>
              <p className="mt-0 mb-2 text-[13px] font-semibold text-slate-600">
                Preview (first 5 rows)
              </p>
              <div className="overflow-x-auto rounded-[10px] border border-slate-200">
                <table className="w-full border-collapse text-xs">
                  <caption className="sr-only">CSV preview — first 5 rows</caption>
                  <thead>
                    <tr className="bg-slate-50">
                      {headers.map((h) => (
                        <th
                          key={h}
                          scope="col"
                          className="py-2 px-3 text-left font-semibold text-slate-500 border-b border-slate-200 whitespace-nowrap"
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.map((row, ri) => (
                      <tr
                        key={ri}
                        style={{
                          borderBottom:
                            ri < preview.length - 1
                              ? `1px solid ${tokens.slate100}`
                              : "none",
                        }}
                      >
                        {headers.map((_, ci) => (
                          <td key={ci} className="py-[7px] px-3 text-slate-900 whitespace-nowrap">
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

          {/* FHIR resource count */}
          {file && format === "fhir" && fhirResourceCount !== null && !result && (
            <div
              style={{
                padding: "14px 18px",
                borderRadius: 10,
                backgroundColor: fhirResourceCount > 0 ? tokens.tealSoft : tokens.dangerSoft,
                border: `1px solid ${fhirResourceCount > 0 ? tokens.tealRing : tokens.dangerBorder}`,
                display: "flex",
                alignItems: "center",
                gap: 10,
              }}
            >
              <CheckCircle
                size={18}
                color={fhirResourceCount > 0 ? tokens.teal700 : tokens.dangerStrong}
              />
              <span
                style={{
                  fontSize: 14,
                  fontWeight: 600,
                  color: fhirResourceCount > 0 ? tokens.teal700 : tokens.dangerAlt,
                }}
              >
                {fhirResourceCount > 0
                  ? `Found ${fhirResourceCount} Patient resource${fhirResourceCount === 1 ? "" : "s"}`
                  : "No Patient resources found in this file"}
              </span>
            </div>
          )}

          {/* Import result */}
          {result && (
            <div
              style={{
                padding: "20px 24px",
                borderRadius: 14,
                backgroundColor: result.errors > 0 ? tokens.warningSoft : tokens.successSoft,
                border: `1px solid ${result.errors > 0 ? tokens.warningBorder : tokens.emerald100}`,
              }}
            >
              <div
                style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}
              >
                <CheckCircle
                  size={20}
                  color={result.errors > 0 ? tokens.riskMedium : tokens.riskLow}
                />
                <span style={{ fontSize: 15, fontWeight: 700, color: tokens.slate900 }}>
                  Import Complete
                </span>
              </div>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns:
                    onDuplicate === "replace"
                      ? "1fr 1fr 1fr 1fr"
                      : "1fr 1fr 1fr 1fr 1fr",
                  gap: 12,
                  marginBottom: result.error_details.length > 0 ? 16 : 0,
                }}
              >
                {[
                  {
                    label: "Total Rows",
                    value: result.total_rows,
                    color: tokens.slate600,
                  },
                  ...(onDuplicate === "replace"
                    ? [
                        {
                          label: "Deleted (old)",
                          value: result.deleted ?? 0,
                          color: tokens.dangerStrong,
                        },
                      ]
                    : []),
                  { label: "Imported", value: result.imported, color: tokens.riskLow },
                  ...(onDuplicate !== "replace"
                    ? [{ label: "Updated", value: result.updated, color: tokens.skyText }]
                    : []),
                  ...(onDuplicate !== "replace"
                    ? [
                        {
                          label:
                            onDuplicate === "update"
                              ? "Unchanged"
                              : "Skipped (dup)",
                          value: result.duplicates_skipped,
                          color: tokens.slate500,
                        },
                      ]
                    : []),
                  {
                    label: "Errors",
                    value: result.errors,
                    color:
                      result.errors > 0 ? tokens.dangerStrong : tokens.slate400,
                  },
                ].map(({ label, value, color }) => (
                  <div key={label} className="text-center">
                    <div
                      style={{
                        fontSize: 22,
                        fontWeight: 700,
                        color,
                        fontVariantNumeric: "tabular-nums",
                      }}
                    >
                      {value}
                    </div>
                    <div className="text-[11px] text-slate-400 mt-0.5">{label}</div>
                  </div>
                ))}
              </div>
              {result.error_details.length > 0 && (
                <div
                  style={{
                    maxHeight: 140,
                    overflowY: "auto",
                    padding: "10px 12px",
                    backgroundColor: "rgba(255,255,255,0.7)",
                    borderRadius: 8,
                    border: `1px solid ${tokens.warningBorder}`,
                  }}
                >
                  {result.error_details.map((e, i) => (
                    <p key={`err-${i}`} className="mb-1 mt-0 text-xs text-amber-900">
                      {e}
                    </p>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-2.5">
            <button
              onClick={onClose}
              className="py-[9px] px-5 rounded-[10px] border border-slate-200 bg-white text-sm font-medium text-slate-600 cursor-pointer"
            >
              {result ? "Close" : "Cancel"}
            </button>
            {!result && (
              <button
                onClick={handleImport}
                disabled={!file || uploading}
                style={{
                  padding: "9px 22px",
                  borderRadius: 10,
                  border: "none",
                  backgroundColor: !file || uploading ? tokens.slate400 : tokens.teal700,
                  color: tokens.white,
                  fontSize: 14,
                  fontWeight: 600,
                  cursor: !file || uploading ? "not-allowed" : "pointer",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 7,
                  boxShadow:
                    !file || uploading ? "none" : "0 4px 10px rgba(15,118,110,0.2)",
                }}
              >
                {uploading ? (
                  <>
                    <span
                      style={{
                        width: 14,
                        height: 14,
                        borderRadius: "50%",
                        border: "2px solid rgba(255,255,255,0.3)",
                        borderTopColor: "#fff",
                        display: "inline-block",
                        animation: "spin 0.7s linear infinite",
                      }}
                    />
                    Importing…
                  </>
                ) : (
                  <>
                    <Upload size={14} /> Import Patients
                  </>
                )}
              </button>
            )}
          </div>
        </div>
      </FocusTrap>
    </div>
  );
}
