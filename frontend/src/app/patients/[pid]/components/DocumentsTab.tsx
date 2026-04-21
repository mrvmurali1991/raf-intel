"use client";

import React, { useState, useMemo, useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  FileUp,
  FileText,
  Upload,
  CheckCircle2,
  XCircle,
  Eye,
  Brain,
  Paperclip,
  FlaskConical,
  Stethoscope,
  ClipboardList,
  TrendingUp,
} from "lucide-react";
import type { MEATEvidence } from "@/types";
import api from "@/lib/api";
import type { DocumentsResponse, DocumentItem } from "@/lib/api";
import {
  uploadPatientDocument,
  getDocumentAnalysis,
  getDocumentDiagnoses,
  confirmDocumentDiagnosis,
  rejectDocumentDiagnosis,
  getDocumentDraftRAF,
  analyzeDocument,
} from "@/lib/api";
import { useToast } from "@/components/Toast";
import {
  C,
  formatDate,
  rafScoreColor,
  Spinner,
  SectionLoader,
  Card,
  MeatDots,
} from "./shared";
import type { DocumentAnalysisData, DraftRAFData } from "./shared";

const REPORT_TYPES = [
  "Lab Report",
  "Medical Report",
  "Wellness Report",
  "Care Report",
  "Discharge Summary",
  "Radiology",
  "Custom Report",
];

const DOC_STATUS_STYLES: Record<string, { bg: string; color: string; label: string }> = {
  analyzed: { bg: C.emerald100, color: C.emerald600, label: "Analyzed" },
  processing: { bg: C.blue100, color: C.blue600, label: "Processing" },
  pending: { bg: C.amber100, color: C.amber600, label: "Pending" },
  failed: { bg: C.red100, color: C.red600, label: "Failed" },
};

export function DocumentsTab({
  pid,
  documents,
  documentsLoading,
  rafScore,
  patientName,
  selectedYear,
}: {
  pid: string;
  documents: DocumentsResponse | undefined;
  documentsLoading: boolean;
  rafScore: number | null;
  patientName: string;
  selectedYear: number;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [reportType, setReportType] = useState("Medical Report");
  const [encounterDate, setEncounterDate] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [expandedAnalysis, setExpandedAnalysis] = useState<number | null>(null);
  const [expandedDraft, setExpandedDraft] = useState<number | null>(null);
  const [analysisData, setAnalysisData] = useState<Record<number, DocumentAnalysisData>>({});
  const [draftData, setDraftData] = useState<Record<number, DraftRAFData>>({});

  const uploadMutation = useMutation({
    mutationFn: async () => {
      if (!selectedFile) throw new Error("No file selected");
      return uploadPatientDocument(pid, selectedFile, reportType, encounterDate || undefined);
    },
    onSuccess: () => {
      toast.success("Upload Complete", "Document has been uploaded and queued for analysis.");
      queryClient.invalidateQueries({ queryKey: ["patient-documents", pid] });
      setSelectedFile(null);
      setEncounterDate("");
      if (fileInputRef.current) fileInputRef.current.value = "";
    },
    onError: () => toast.error("Upload Failed", "Could not upload the document. Please try again."),
  });

  const analyzeMut = useMutation({
    mutationFn: (docId: number) => analyzeDocument(docId),
    onSuccess: () => {
      toast.success("Analysis Started", "Document is being analyzed.");
      queryClient.invalidateQueries({ queryKey: ["patient-documents", pid] });
    },
    onError: () => toast.error("Error", "Failed to start analysis."),
  });

  const confirmDxMut = useMutation({
    mutationFn: ({ docId, dxId }: { docId: number; dxId: number }) =>
      confirmDocumentDiagnosis(docId, dxId),
    onSuccess: (_data, vars) => {
      toast.success("Confirmed", "Diagnosis has been confirmed.");
      fetchAnalysis(vars.docId);
    },
    onError: () => toast.error("Error", "Failed to confirm diagnosis."),
  });

  const rejectDxMut = useMutation({
    mutationFn: ({ docId, dxId }: { docId: number; dxId: number }) =>
      rejectDocumentDiagnosis(docId, dxId),
    onSuccess: (_data, vars) => {
      toast.success("Rejected", "Diagnosis has been rejected.");
      fetchAnalysis(vars.docId);
    },
    onError: () => toast.error("Error", "Failed to reject diagnosis."),
  });

  async function fetchAnalysis(docId: number) {
    try {
      const [analysis, diagnoses] = await Promise.all([
        getDocumentAnalysis(docId),
        getDocumentDiagnoses(docId),
      ]);
      setAnalysisData((prev) => ({ ...prev, [docId]: { ...analysis, diagnoses } }));
    } catch {
      toast.error("Error", "Failed to load analysis.");
    }
  }

  async function fetchDraftRAF(docId: number) {
    try {
      const draft = await getDocumentDraftRAF(docId);
      setDraftData((prev) => ({ ...prev, [docId]: draft }));
    } catch {
      toast.error("Error", "Failed to calculate draft RAF score.");
    }
  }

  function handleViewAnalysis(docId: number) {
    if (expandedAnalysis === docId) { setExpandedAnalysis(null); return; }
    setExpandedAnalysis(docId);
    setExpandedDraft(null);
    if (!analysisData[docId]) fetchAnalysis(docId);
  }

  function handleDraftRAF(docId: number) {
    if (expandedDraft === docId) { setExpandedDraft(null); return; }
    setExpandedDraft(docId);
    setExpandedAnalysis(null);
    if (!draftData[docId]) fetchDraftRAF(docId);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) setSelectedFile(file);
  }

  const docList = useMemo(() => {
    const all = documents?.documents ?? [];
    return all.filter((d: DocumentItem) => {
      const dateStr = d.upload_date || d.created_at || (d as DocumentItem & { encounter_date?: string }).encounter_date;
      if (!dateStr) return true;
      return new Date(dateStr).getFullYear() === selectedYear;
    });
  }, [documents, selectedYear]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* UPLOAD SECTION */}
      <Card className="hover-lift">
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 10,
            background: `linear-gradient(135deg, ${C.blue600}, ${C.emerald600})`,
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <FileUp size={18} color="#fff" />
          </div>
          <div>
            <h3 style={{ fontSize: 16, fontWeight: 700, color: C.slate900, margin: 0 }}>Upload Document</h3>
            <p style={{ fontSize: 12, color: C.slate500, margin: 0 }}>
              Upload lab reports, medical records, or clinical documents for AI analysis
            </p>
          </div>
        </div>

        {/* Drop zone */}
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          style={{
            border: `2px dashed ${dragOver ? C.blue600 : C.slate300}`,
            borderRadius: 12, padding: selectedFile ? "16px 24px" : "40px 24px",
            textAlign: "center", cursor: "pointer",
            background: dragOver ? C.blue50 : C.slate100,
            transition: "all 0.2s ease", marginBottom: 16,
          }}
        >
          <input
            ref={fileInputRef} type="file" accept=".pdf,.png,.jpg,.jpeg,.doc,.docx"
            style={{ display: "none" }}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) setSelectedFile(f); }}
          />
          {selectedFile ? (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 12 }}>
              <Paperclip size={18} color={C.blue600} />
              <span style={{ fontSize: 14, fontWeight: 600, color: C.slate800 }}>{selectedFile.name}</span>
              <span style={{ fontSize: 12, color: C.slate500 }}>({(selectedFile.size / 1024).toFixed(1)} KB)</span>
              <button
                onClick={(e) => { e.stopPropagation(); setSelectedFile(null); if (fileInputRef.current) fileInputRef.current.value = ""; }}
                style={{ background: "none", border: "none", cursor: "pointer", color: C.red500, padding: 4 }}
              >
                <XCircle size={16} />
              </button>
            </div>
          ) : (
            <>
              <Upload size={32} color={C.slate400} style={{ marginBottom: 8 }} />
              <p style={{ fontSize: 14, fontWeight: 600, color: C.slate700, margin: "4px 0" }}>
                Drop a file here or click to browse
              </p>
              <p style={{ fontSize: 12, color: C.slate400, margin: 0 }}>PDF, PNG, JPG, DOC up to 25 MB</p>
            </>
          )}
        </div>

        {/* Report type pills */}
        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 12, fontWeight: 600, color: C.slate600, marginBottom: 8, display: "block" }}>Report Type</label>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {REPORT_TYPES.map((rt) => (
              <button
                key={rt} onClick={() => setReportType(rt)} className="btn-press"
                style={{
                  padding: "6px 14px", borderRadius: 20,
                  border: `1.5px solid ${reportType === rt ? C.blue600 : C.slate300}`,
                  background: reportType === rt ? C.blue50 : C.white,
                  color: reportType === rt ? C.blue600 : C.slate600,
                  fontSize: 12, fontWeight: 600, cursor: "pointer", transition: "all 0.15s ease",
                }}
              >
                {rt}
              </button>
            ))}
          </div>
        </div>

        {/* Encounter date + Upload button */}
        <div style={{ display: "flex", alignItems: "flex-end", gap: 12, flexWrap: "wrap" }}>
          <div>
            <label style={{ fontSize: 12, fontWeight: 600, color: C.slate600, marginBottom: 4, display: "block" }}>
              Encounter Date (optional)
            </label>
            <input
              type="date" value={encounterDate}
              onChange={(e) => setEncounterDate(e.target.value)}
              style={{
                padding: "8px 12px", borderRadius: 8, border: `1px solid ${C.slate300}`,
                fontSize: 13, color: C.slate800, background: C.white, outline: "none",
              }}
            />
          </div>
          <button
            onClick={() => uploadMutation.mutate()}
            disabled={!selectedFile || uploadMutation.isPending}
            className="btn-press"
            style={{
              padding: "9px 24px", borderRadius: 10, border: "none",
              background: !selectedFile ? C.slate300 : `linear-gradient(135deg, ${C.blue600}, ${C.emerald600})`,
              color: C.white, fontSize: 13, fontWeight: 700,
              cursor: selectedFile ? "pointer" : "not-allowed",
              display: "flex", alignItems: "center", gap: 8,
              transition: "all 0.2s ease", opacity: uploadMutation.isPending ? 0.7 : 1,
            }}
          >
            {uploadMutation.isPending ? (<><Spinner size={14} /> Uploading...</>) : (<><FileUp size={14} /> Upload &amp; Analyze</>)}
          </button>
        </div>
      </Card>

      {/* DOCUMENTS LIST */}
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
          <ClipboardList size={18} color={C.blue600} />
          <h3 style={{ fontSize: 16, fontWeight: 700, color: C.slate900, margin: 0 }}>Uploaded Documents</h3>
          <span className="tabular-nums" style={{ fontSize: 11, fontWeight: 700, background: C.blue100, color: C.blue600, padding: "2px 8px", borderRadius: 10 }}>
            {docList.length}
          </span>
        </div>

        {documentsLoading ? (
          <SectionLoader label="Loading documents..." />
        ) : docList.length === 0 ? (
          <Card>
            <div style={{ textAlign: "center", padding: "48px 24px" }}>
              <FileText size={40} color={C.slate300} style={{ marginBottom: 12 }} />
              <p style={{ fontSize: 15, fontWeight: 600, color: C.slate500, margin: "0 0 4px" }}>No documents yet</p>
              <p style={{ fontSize: 13, color: C.slate400, margin: 0 }}>
                Upload a document above to get started with AI-powered analysis
              </p>
            </div>
          </Card>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {docList.map((doc: DocumentItem, idx: number) => {
              const status = DOC_STATUS_STYLES[doc.status] ?? DOC_STATUS_STYLES.pending;
              const docId = doc.id ?? doc.document_id;
              const isAnalysisOpen = expandedAnalysis === docId;
              const isDraftOpen = expandedDraft === docId;
              const aData = analysisData[docId];
              const dData = draftData[docId];

              return (
                <div key={docId} className={`animate-fade-in stagger-${Math.min(idx + 1, 5)}`} style={{ display: "flex", flexDirection: "column", gap: 0 }}>
                  <Card className="hover-lift" style={{ transition: "all 0.2s ease" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                      <div style={{
                        width: 40, height: 40, borderRadius: 10,
                        background: `${C.blue600}15`,
                        display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
                      }}>
                        <FileText size={18} color={C.blue600} />
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                          <span style={{ fontSize: 14, fontWeight: 700, color: C.slate900 }}>
                            {doc.filename || doc.file_name || "Document"}
                          </span>
                          <span style={{ padding: "2px 8px", borderRadius: 10, fontSize: 10, fontWeight: 700, background: status.bg, color: status.color }}>
                            {status.label}
                          </span>
                        </div>
                        <div style={{ display: "flex", gap: 16, marginTop: 4, flexWrap: "wrap" }}>
                          <span style={{ fontSize: 12, color: C.slate400 }}>{doc.report_type || reportType}</span>
                          <span style={{ fontSize: 12, color: C.slate400 }}>{formatDate(doc.created_at || doc.upload_date)}</span>
                          {doc.diagnosis_count != null && doc.diagnosis_count > 0 && (
                            <span style={{ fontSize: 12, color: C.emerald600, fontWeight: 600 }}>{doc.diagnosis_count} diagnoses</span>
                          )}
                        </div>
                      </div>
                      <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                        <button
                          onClick={() => {
                            api.get(`/api/documents/${docId}/view`, { responseType: "blob" })
                              .then((res) => {
                                const url = URL.createObjectURL(res.data as Blob);
                                window.open(url, "_blank");
                                setTimeout(() => URL.revokeObjectURL(url), 60_000);
                              })
                              .catch(() => {});
                          }}
                          className="btn-press"
                          style={{
                            padding: "6px 12px", borderRadius: 8, border: `1px solid ${C.slate300}`,
                            background: C.white, color: C.slate600, fontSize: 12, fontWeight: 600,
                            cursor: "pointer", display: "flex", alignItems: "center", gap: 4, transition: "all 0.15s",
                          }}
                        >
                          <FileText size={13} /> View
                        </button>
                        {doc.status === "analyzed" && (
                          <>
                            <button
                              onClick={() => handleViewAnalysis(docId)}
                              className="btn-press"
                              style={{
                                padding: "6px 12px", borderRadius: 8,
                                border: `1px solid ${isAnalysisOpen ? C.blue600 : C.slate300}`,
                                background: isAnalysisOpen ? C.blue50 : C.white,
                                color: isAnalysisOpen ? C.blue600 : C.slate600,
                                fontSize: 12, fontWeight: 600, cursor: "pointer",
                                display: "flex", alignItems: "center", gap: 4, transition: "all 0.15s",
                              }}
                            >
                              <Eye size={13} /> Analysis
                            </button>
                            <button
                              onClick={() => handleDraftRAF(docId)}
                              className="btn-press"
                              style={{
                                padding: "6px 12px", borderRadius: 8,
                                border: `1px solid ${isDraftOpen ? C.emerald600 : C.slate300}`,
                                background: isDraftOpen ? C.emerald50 : C.white,
                                color: isDraftOpen ? C.emerald600 : C.slate600,
                                fontSize: 12, fontWeight: 600, cursor: "pointer",
                                display: "flex", alignItems: "center", gap: 4, transition: "all 0.15s",
                              }}
                            >
                              <TrendingUp size={13} /> Draft Score
                            </button>
                          </>
                        )}
                        {(doc.status === "pending" || doc.status === "failed") && (
                          <button
                            onClick={() => analyzeMut.mutate(docId)}
                            disabled={analyzeMut.isPending}
                            className="btn-press"
                            style={{
                              padding: "6px 12px", borderRadius: 8, border: "none",
                              background: `linear-gradient(135deg, ${C.blue600}, ${C.emerald600})`,
                              color: C.white, fontSize: 12, fontWeight: 600, cursor: "pointer",
                              display: "flex", alignItems: "center", gap: 4,
                            }}
                          >
                            <Brain size={13} /> Analyze
                          </button>
                        )}
                      </div>
                    </div>
                  </Card>

                  {/* ANALYSIS PANEL */}
                  {isAnalysisOpen && (
                    <div className="animate-slide-up" style={{ marginTop: -1 }}>
                      <Card className="card-glow-blue" style={{ borderTopLeftRadius: 0, borderTopRightRadius: 0, borderTop: `2px solid ${C.blue600}` }}>
                        {!aData ? (
                          <SectionLoader label="Loading analysis..." />
                        ) : (
                          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
                            {aData.summary && (
                              <div>
                                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
                                  <Stethoscope size={14} color={C.blue600} />
                                  <span style={{ fontSize: 13, fontWeight: 700, color: C.slate800 }}>Clinical Summary</span>
                                </div>
                                <p style={{ fontSize: 13, color: C.slate600, lineHeight: 1.6, margin: 0, background: C.slate100, padding: 12, borderRadius: 8 }}>
                                  {aData.summary}
                                </p>
                              </div>
                            )}

                            <div>
                              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 10 }}>
                                <ClipboardList size={14} color={C.emerald600} />
                                <span style={{ fontSize: 13, fontWeight: 700, color: C.slate800 }}>Extracted Diagnoses</span>
                                <span className="tabular-nums" style={{ fontSize: 11, fontWeight: 700, background: C.emerald100, color: C.emerald600, padding: "1px 6px", borderRadius: 8 }}>
                                  {aData.diagnoses?.length ?? 0}
                                </span>
                              </div>

                              {(!aData.diagnoses || aData.diagnoses.length === 0) ? (
                                <p style={{ fontSize: 13, color: C.slate400, fontStyle: "italic" }}>No diagnoses extracted.</p>
                              ) : (
                                <div style={{ overflowX: "auto" }}>
                                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                                    <thead>
                                      <tr style={{ borderBottom: `2px solid ${C.slate200}` }}>
                                        {["ICD-10", "Description", "HCC", "RAF Weight", "Confidence", "MEAT", "Actions"].map((h) => (
                                          <th key={h} style={{
                                            textAlign: "left", padding: "8px 10px", fontSize: 11, fontWeight: 700,
                                            color: C.slate500, textTransform: "uppercase", letterSpacing: "0.5px",
                                          }}>
                                            {h}
                                          </th>
                                        ))}
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {aData.diagnoses.map((dx, i: number) => (
                                        <tr key={dx.id ?? i} style={{
                                          borderBottom: `1px solid ${C.slate100}`,
                                          background: dx.status === "confirmed" ? `${C.emerald600}08` : dx.status === "rejected" ? `${C.red600}08` : "transparent",
                                        }}>
                                          <td style={{ padding: "10px", fontWeight: 700, color: C.blue600, fontFamily: "monospace" }}>
                                            {dx.icd10_code || dx.icd_code || "--"}
                                          </td>
                                          <td style={{ padding: "10px", color: C.slate700, maxWidth: 240 }}>
                                            {dx.description || dx.diagnosis || "--"}
                                          </td>
                                          <td style={{ padding: "10px" }}>
                                            {dx.hcc_code ? (
                                              <span style={{ padding: "2px 6px", borderRadius: 6, background: C.amber100, color: C.amber600, fontSize: 11, fontWeight: 700 }}>
                                                {dx.hcc_code}
                                              </span>
                                            ) : <span style={{ color: C.slate400 }}>--</span>}
                                          </td>
                                          <td className="tabular-nums" style={{ padding: "10px", fontWeight: 700, color: C.slate800 }}>
                                            {dx.raf_weight != null ? (dx.raf_weight ?? 0).toFixed(3) : "--"}
                                          </td>
                                          <td style={{ padding: "10px" }}>
                                            {dx.confidence != null ? (
                                              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                                <div style={{ width: 40, height: 5, borderRadius: 3, background: C.slate200, overflow: "hidden" }}>
                                                  <div style={{
                                                    width: `${Math.round((dx.confidence ?? 0) * 100)}%`, height: "100%", borderRadius: 3,
                                                    background: (dx.confidence ?? 0) >= 0.8 ? C.emerald500 : (dx.confidence ?? 0) >= 0.5 ? C.amber500 : C.red500,
                                                  }} />
                                                </div>
                                                <span className="tabular-nums" style={{ fontSize: 11, color: C.slate500, fontWeight: 600 }}>
                                                  {Math.round((dx.confidence ?? 0) * 100)}%
                                                </span>
                                              </div>
                                            ) : <span style={{ color: C.slate400 }}>--</span>}
                                          </td>
                                          <td style={{ padding: "10px" }}>
                                            <MeatDots evidence={dx.meat_evidence ?? (dx.meat as MEATEvidence | undefined)} />
                                          </td>
                                          <td style={{ padding: "10px" }}>
                                            {dx.status === "confirmed" ? (
                                              <span style={{ fontSize: 11, fontWeight: 700, color: C.emerald600 }}>Confirmed</span>
                                            ) : dx.status === "rejected" ? (
                                              <span style={{ fontSize: 11, fontWeight: 700, color: C.red600 }}>Rejected</span>
                                            ) : (
                                              <div style={{ display: "flex", gap: 4 }}>
                                                <button
                                                  onClick={() => confirmDxMut.mutate({ docId, dxId: dx.id! })}
                                                  className="btn-press"
                                                  style={{
                                                    padding: "4px 8px", borderRadius: 6, border: `1px solid ${C.emerald600}`,
                                                    background: C.emerald50, color: C.emerald600, fontSize: 11, fontWeight: 700,
                                                    cursor: "pointer", display: "flex", alignItems: "center", gap: 3,
                                                  }}
                                                >
                                                  <CheckCircle2 size={11} /> Confirm
                                                </button>
                                                <button
                                                  onClick={() => rejectDxMut.mutate({ docId, dxId: dx.id! })}
                                                  className="btn-press"
                                                  style={{
                                                    padding: "4px 8px", borderRadius: 6, border: `1px solid ${C.red500}`,
                                                    background: C.red50, color: C.red600, fontSize: 11, fontWeight: 700,
                                                    cursor: "pointer", display: "flex", alignItems: "center", gap: 3,
                                                  }}
                                                >
                                                  <XCircle size={11} /> Reject
                                                </button>
                                              </div>
                                            )}
                                          </td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
                              )}
                            </div>

                            {/* Medications / Labs / Vitals */}
                            <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
                              {aData.medications && aData.medications.length > 0 && (
                                <div style={{ flex: "1 1 200px" }}>
                                  <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 6 }}>
                                    <FlaskConical size={13} color={C.purple600} />
                                    <span style={{ fontSize: 12, fontWeight: 700, color: C.slate700 }}>Medications</span>
                                  </div>
                                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                                    {aData.medications.map((med: string, i: number) => (
                                      <span key={med || i} style={{ padding: "2px 8px", borderRadius: 6, background: C.slate100, fontSize: 11, color: C.slate600 }}>{med}</span>
                                    ))}
                                  </div>
                                </div>
                              )}
                              {aData.labs && aData.labs.length > 0 && (
                                <div style={{ flex: "1 1 200px" }}>
                                  <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 6 }}>
                                    <FlaskConical size={13} color={C.amber600} />
                                    <span style={{ fontSize: 12, fontWeight: 700, color: C.slate700 }}>Labs</span>
                                  </div>
                                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                                    {aData.labs.map((lab: string | { name: string; value: string }, i: number) => (
                                      <span key={typeof lab === "string" ? lab : `${lab.name}-${i}`} style={{ padding: "2px 8px", borderRadius: 6, background: C.amber50, fontSize: 11, color: C.amber600 }}>
                                        {typeof lab === "string" ? lab : `${lab.name}: ${lab.value}`}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              )}
                              {aData.vitals && aData.vitals.length > 0 && (
                                <div style={{ flex: "1 1 200px" }}>
                                  <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 6 }}>
                                    <Stethoscope size={13} color={C.red500} />
                                    <span style={{ fontSize: 12, fontWeight: 700, color: C.slate700 }}>Vitals</span>
                                  </div>
                                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                                    {aData.vitals.map((v: string | { name: string; value: string }, i: number) => (
                                      <span key={typeof v === "string" ? v : `${v.name}-${i}`} style={{ padding: "2px 8px", borderRadius: 6, background: C.red50, fontSize: 11, color: C.red600 }}>
                                        {typeof v === "string" ? v : `${v.name}: ${v.value}`}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              )}
                            </div>
                          </div>
                        )}
                      </Card>
                    </div>
                  )}

                  {/* DRAFT RAF PANEL */}
                  {isDraftOpen && (
                    <div className="animate-slide-up" style={{ marginTop: -1 }}>
                      <Card className="card-glow-emerald" style={{ borderTopLeftRadius: 0, borderTopRightRadius: 0, borderTop: `2px solid ${C.emerald600}` }}>
                        {!dData ? (
                          <SectionLoader label="Calculating draft RAF score..." />
                        ) : (
                          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
                            {/* Score comparison */}
                            <div style={{ display: "flex", gap: 24, flexWrap: "wrap", justifyContent: "center" }}>
                              <div style={{ textAlign: "center", minWidth: 140 }}>
                                <p style={{ fontSize: 11, fontWeight: 700, color: C.slate500, textTransform: "uppercase", letterSpacing: 1, margin: "0 0 6px" }}>Current RAF</p>
                                <span className="tabular-nums" style={{ fontSize: 36, fontWeight: 800, color: rafScoreColor(rafScore ?? 0), lineHeight: 1 }}>
                                  {(rafScore ?? 0).toFixed(3)}
                                </span>
                              </div>
                              <div style={{ display: "flex", alignItems: "center", color: C.slate400, fontSize: 28, fontWeight: 300 }}>&rarr;</div>
                              <div style={{ textAlign: "center", minWidth: 140 }}>
                                <p style={{ fontSize: 11, fontWeight: 700, color: C.slate500, textTransform: "uppercase", letterSpacing: 1, margin: "0 0 6px" }}>Draft RAF</p>
                                <span className="tabular-nums" style={{
                                  fontSize: 36, fontWeight: 800, lineHeight: 1,
                                  background: `linear-gradient(135deg, ${C.blue600}, ${C.emerald600})`,
                                  WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
                                }}>
                                  {(dData.draft_raf ?? dData.draft_score ?? 0).toFixed(3)}
                                </span>
                              </div>
                              <div style={{ textAlign: "center", minWidth: 120 }}>
                                <p style={{ fontSize: 11, fontWeight: 700, color: C.slate500, textTransform: "uppercase", letterSpacing: 1, margin: "0 0 6px" }}>Delta</p>
                                <span className="tabular-nums" style={{ fontSize: 36, fontWeight: 800, color: C.emerald600, lineHeight: 1 }}>
                                  +{((dData.draft_raf ?? dData.draft_score ?? 0) - (rafScore ?? 0)).toFixed(3)}
                                </span>
                              </div>
                            </div>

                            {/* New HCC codes */}
                            {(dData.new_hccs ?? dData.new_hcc_codes ?? []).length > 0 && (
                              <div>
                                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
                                  <Brain size={14} color={C.blue600} />
                                  <span style={{ fontSize: 13, fontWeight: 700, color: C.slate800 }}>New HCC Codes</span>
                                </div>
                                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                                  {(dData.new_hccs ?? dData.new_hcc_codes ?? []).map((hcc: string | { code?: string; hcc_code?: string; label?: string; description?: string; coefficient?: number; raf_weight?: number }, i: number) => (
                                    <div key={typeof hcc === "string" ? hcc : (hcc.hcc_code || hcc.code || `hcc-${i}`)} style={{
                                      padding: "6px 12px", borderRadius: 8, background: C.emerald50,
                                      border: `1px solid ${C.emerald100}`, display: "flex", alignItems: "center", gap: 6,
                                    }}>
                                      <span style={{ fontSize: 12, fontWeight: 800, color: C.emerald600, fontFamily: "monospace" }}>
                                        {typeof hcc === "string" ? hcc : hcc.code ?? hcc.hcc_code}
                                      </span>
                                      {typeof hcc === "object" && hcc.description && (
                                        <span style={{ fontSize: 11, color: C.slate500 }}>{hcc.description}</span>
                                      )}
                                      {typeof hcc === "object" && hcc.raf_weight != null && (
                                        <span className="tabular-nums" style={{ fontSize: 11, fontWeight: 700, color: C.blue600 }}>
                                          +{(hcc.raf_weight ?? 0).toFixed(3)}
                                        </span>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}

                            {/* Revenue impact */}
                            {(dData.estimated_revenue_impact ?? dData.revenue_impact) != null && (
                              <div style={{
                                background: `linear-gradient(135deg, ${C.emerald50}, ${C.blue50})`,
                                padding: "14px 18px", borderRadius: 10,
                                display: "flex", alignItems: "center", gap: 10,
                              }}>
                                <TrendingUp size={18} color={C.emerald600} />
                                <div>
                                  <span style={{ fontSize: 12, color: C.slate500, fontWeight: 600 }}>Estimated Revenue Impact</span>
                                  <span className="tabular-nums" style={{ display: "block", fontSize: 22, fontWeight: 800, color: C.emerald600 }}>
                                    ${((dData.estimated_revenue_impact ?? dData.revenue_impact ?? 0)).toLocaleString()}
                                  </span>
                                </div>
                              </div>
                            )}

                            <p style={{ fontSize: 11, color: C.slate400, fontStyle: "italic", margin: 0, padding: "8px 12px", background: C.slate100, borderRadius: 8 }}>
                              This is a preliminary score based on document-extracted diagnoses. Final RAF scores are subject to CMS adjudication and may differ from this estimate.
                            </p>
                          </div>
                        )}
                      </Card>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
