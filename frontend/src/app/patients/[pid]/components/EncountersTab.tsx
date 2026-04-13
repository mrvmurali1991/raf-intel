"use client";

import React, { useState, useMemo } from "react";
import type { AnalysisResult, AIDiagnosis } from "@/types";
import type { PatientEncountersResponse } from "@/lib/api";
import {
  EmptyState,
  ConfidencePill,
} from "@/components/healthcare-ui";
import {
  C,
  formatDate,
  Spinner,
  SectionLoader,
  Card,
  MeatDots,
} from "./shared";
import type { EncounterItem } from "./shared";
import { LLMInputPanel } from "./RAFTab";

export function EncountersTab({ encounters, encountersLoading, analyzeMutation, lastAnalysisResult, selectedYear }: {
  encounters: PatientEncountersResponse | undefined;
  encountersLoading: boolean;
  analyzeMutation: { mutate: (encId: number) => void; isPending: boolean; variables?: number };
  lastAnalysisResult: Record<number, AnalysisResult>;
  selectedYear: number;
}) {
  const [expandedEnc, setExpandedEnc] = useState<number | null>(null);

  const filteredEncounters = useMemo(() => {
    if (!encounters?.encounters) return [];
    return encounters.encounters.filter((enc: EncounterItem) => {
      const encDate = enc.date || enc.encounter_date;
      if (!encDate) return true;
      const encYear = new Date(encDate).getFullYear();
      return encYear === selectedYear;
    });
  }, [encounters, selectedYear]);

  if (encountersLoading) return <SectionLoader label="Loading encounters..." />;
  if (!filteredEncounters.length) {
    return (
      <Card>
        <EmptyState
          title={`No encounters found for ${selectedYear}`}
          icon={
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
            </svg>
          }
        />
      </Card>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {filteredEncounters.map((enc: EncounterItem) => {
        const isExpanded = expandedEnc === enc.encounter_id;
        const hasNotes = !!enc.notes || !!enc.has_notes;
        const analysis = enc.analysis || enc.cached_analysis || lastAnalysisResult?.[enc.encounter_id];
        const diagnoses = analysis?.diagnoses || [];
        const hccFromAnalysis = diagnoses.filter(
          (d: AIDiagnosis) => d.hcc_code || d.hcc || d.hcc_mapping?.hcc_code
        ).length;

        return (
          <Card key={enc.encounter_id} noPadding className="hover-lift animate-fade-in" style={{ overflow: "hidden" }}>
            {/* Header row */}
            <div
              role="button"
              tabIndex={0}
              onClick={() => setExpandedEnc(isExpanded ? null : enc.encounter_id)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setExpandedEnc(isExpanded ? null : enc.encounter_id); } }}
              style={{
                width: "100%",
                padding: "16px 20px",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                background: "transparent",
                border: "none",
                cursor: "pointer",
                textAlign: "left",
                transition: "background 0.1s",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = C.slate100)}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                <div
                  style={{
                    width: 40, height: 40, borderRadius: 10,
                    background: C.blue50, color: C.blue600,
                    display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
                  }}
                >
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
                  </svg>
                </div>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: C.slate800 }}>
                    {enc.reason || "Office Visit"}
                  </div>
                  <div style={{ fontSize: 12, color: C.slate400, marginTop: 2 }}>
                    {enc.provider_fname || enc.provider_lname
                      ? `${enc.provider_fname || ""} ${enc.provider_lname || ""}`.trim()
                      : "Provider not listed"}
                    {" \u00B7 "}Encounter #{enc.encounter_id}
                  </div>
                </div>
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <span style={{ fontSize: 13, color: C.slate500 }}>
                  {formatDate(enc.date)}
                </span>
                {!hasNotes && (
                  <span style={{
                    display: "inline-flex", alignItems: "center", gap: 4,
                    padding: "3px 10px", borderRadius: 6, fontSize: 11, fontWeight: 600,
                    background: C.amber50, color: C.amber600, border: `1px solid ${C.amber100}`,
                  }}>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01" />
                    </svg>
                    No notes
                  </span>
                )}
                {diagnoses.length > 0 && (
                  <span style={{
                    display: "inline-flex", alignItems: "center", gap: 4,
                    padding: "3px 10px", borderRadius: 6, fontSize: 11, fontWeight: 600,
                    background: C.emerald50, color: C.emerald600, border: `1px solid ${C.emerald100}`,
                  }}>
                    {diagnoses.length} dx{hccFromAnalysis > 0 ? ` / ${hccFromAnalysis} HCC` : ""}
                  </span>
                )}
                <button
                  onClick={(e) => { e.stopPropagation(); analyzeMutation.mutate(enc.encounter_id); }}
                  disabled={analyzeMutation.isPending || !hasNotes}
                  style={{
                    display: "inline-flex", alignItems: "center", gap: 4,
                    padding: "6px 14px", borderRadius: 6,
                    border: `1px solid ${C.slate200}`, background: C.white,
                    color: !hasNotes ? C.slate400 : C.blue600,
                    fontSize: 12, fontWeight: 600,
                    cursor: analyzeMutation.isPending || !hasNotes ? "not-allowed" : "pointer",
                    opacity: analyzeMutation.isPending || !hasNotes ? 0.5 : 1,
                  }}
                >
                  {analyzeMutation.isPending && analyzeMutation.variables === enc.encounter_id ? <Spinner size={12} /> : null}
                  Analyze
                </button>
                <svg
                  width="16" height="16" viewBox="0 0 24 24" fill="none"
                  stroke={C.slate400} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                  style={{ transform: isExpanded ? "rotate(180deg)" : "rotate(0)", transition: "transform 0.2s" }}
                >
                  <polyline points="6 9 12 15 18 9" />
                </svg>
              </div>
            </div>

            {/* Expanded content */}
            {isExpanded && (
              <div style={{ padding: "16px 20px", borderTop: `1px solid ${C.slate200}`, background: C.slate100 + "80" }}>
                {!hasNotes ? (
                  <div style={{ textAlign: "center", padding: "24px 0", color: C.slate400, fontSize: 13 }}>
                    No clinical notes available for this encounter
                  </div>
                ) : diagnoses.length > 0 ? (
                  <div>
                    {/* AI Analysis info banner */}
                    <div style={{
                      display: "flex", alignItems: "center", gap: 10,
                      padding: "10px 14px", marginBottom: 12,
                      background: "linear-gradient(135deg, rgba(59,130,246,0.06), rgba(16,185,129,0.06))",
                      border: `1px solid ${C.blue100}`, borderRadius: 8,
                      fontSize: 12, color: C.slate600, lineHeight: 1.5,
                    }}>
                      <span style={{ fontSize: 16 }}>{"\uD83E\uDD16"}</span>
                      <div>
                        <strong style={{ color: C.slate800 }}>AI Analysis</strong> extracted <strong>{diagnoses.length}</strong> diagnoses
                        {hccFromAnalysis > 0 && <> including <strong style={{ color: C.blue600 }}>{hccFromAnalysis} HCC-carrying codes</strong></>} from
                        this encounter&apos;s SOAP notes. These codes are <strong>not yet in billing</strong> &mdash; review and accept to update claims.
                      </div>
                    </div>
                    {/* LLM Input Data */}
                    {(() => {
                      const llmInput = analysis?.pipeline?.llm_input || (() => {
                        const meta = analysis?._meta || {};
                        const pipeline = analysis?.pipeline || {};
                        const toolCalls = pipeline?.tool_calls || [];
                        const icdCodes = diagnoses.map((d: any) => d.icd10).filter(Boolean);
                        const hccLookups = toolCalls.filter((t: any) => t.function === "lookup_hcc");
                        const medChecks = toolCalls.filter((t: any) => t.function === "check_medication_gaps");
                        return {
                          model: meta.pipeline_version === "skill_v1" ? "ai-engine-v1" : "unknown",
                          patient_age: null, patient_sex: null,
                          clinical_note_chars: pipeline.note_chars_submitted || pipeline.note_chars_original || 0,
                          temperature: 0.0,
                          medications: medChecks.map((t: any) => t.args?.medication).filter(Boolean),
                          existing_hccs: [], problem_list: [], recapture_gaps: [],
                          latest_vitals: {}, med_diagnoses: [], clinical_note_preview: null,
                          _reconstructed: true,
                          tool_calls_summary: {
                            total: toolCalls.length, turns: meta.turns || 0,
                            total_time: meta.total_time_seconds || 0,
                            icd_validated: toolCalls.filter((t: any) => t.function === "validate_icd10").length,
                            hcc_lookups: hccLookups.length, med_checks: medChecks.length,
                            raf_calculated: toolCalls.filter((t: any) => t.function === "calculate_raf_score").length,
                          },
                          extracted_icd_codes: icdCodes,
                        };
                      })();
                      return <LLMInputPanel llmInput={llmInput} />;
                    })()}
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
                      <div style={{ fontSize: 12, fontWeight: 600, color: C.slate500, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                        AI-Extracted Diagnoses
                      </div>
                      <span style={{
                        display: "inline-flex", alignItems: "center", gap: 4,
                        padding: "3px 10px", borderRadius: 999, fontSize: 10, fontWeight: 700,
                        background: C.emerald50, color: C.emerald600, border: `1px solid ${C.emerald100}`,
                        textTransform: "uppercase", letterSpacing: "0.03em",
                      }}>
                        Source: AI Analysis
                      </span>
                    </div>
                    <div style={{
                      display: "grid", gridTemplateColumns: "1fr 100px 80px 100px 80px",
                      padding: "8px 16px", background: C.white,
                      borderRadius: "8px 8px 0 0", border: `1px solid ${C.slate200}`, borderBottom: "none", gap: 8,
                    }}>
                      {["Diagnosis", "ICD-10", "HCC", "Confidence", "MEAT"].map((h) => (
                        <span key={h} style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: C.slate400 }}>
                          {h}
                        </span>
                      ))}
                    </div>
                    {diagnoses.map((dx: AIDiagnosis, i: number) => {
                      const hcc = dx.hcc_code || dx.hcc || dx.hcc_mapping?.hcc_code;
                      const confidence = dx.confidence_score ?? dx.confidence ?? 0;
                      return (
                        <div
                          key={dx.icd10 || dx.icd10_code || `dx-${i}`}
                          style={{
                            display: "grid", gridTemplateColumns: "1fr 100px 80px 100px 80px",
                            padding: "10px 16px", background: C.white,
                            border: `1px solid ${C.slate200}`, borderTop: "none",
                            borderRadius: i === diagnoses.length - 1 ? "0 0 8px 8px" : 0, gap: 8,
                          }}
                        >
                          <span style={{ fontSize: 13, fontWeight: 500, color: C.slate800 }}>
                            {dx.condition || dx.diagnosis || dx.description || "\u2014"}
                          </span>
                          <span>
                            <span style={{
                              display: "inline-block", padding: "2px 6px", borderRadius: 4,
                              fontSize: 11, fontWeight: 600, fontFamily: "monospace",
                              background: C.slate100, color: C.slate700, border: `1px solid ${C.slate200}`,
                            }}>
                              {dx.icd10_code || dx.code || "\u2014"}
                            </span>
                          </span>
                          <span>
                            {hcc && (
                              <span style={{
                                display: "inline-block", padding: "2px 6px", borderRadius: 4,
                                fontSize: 11, fontWeight: 600, fontFamily: "monospace",
                                background: C.blue50, color: C.blue600, border: `1px solid ${C.blue100}`,
                              }}>
                                {hcc}
                              </span>
                            )}
                          </span>
                          <span><ConfidencePill value={confidence} /></span>
                          <span><MeatDots evidence={dx.meat_evidence || dx.meat} /></span>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div style={{ textAlign: "center", padding: "24px 0", color: C.slate500, fontSize: 13 }}>
                    <strong>Not analyzed yet.</strong> Click &ldquo;Analyze&rdquo; or &ldquo;Analyze All Encounters&rdquo; to run AI extraction on this encounter&apos;s SOAP notes. The AI will identify ICD-10 codes and HCC opportunities from the clinical documentation.
                  </div>
                )}

                {/* Show notes if present */}
                {enc.notes && (
                  <div style={{ marginTop: 12, padding: 16, background: C.white, borderRadius: 8, border: `1px solid ${C.slate200}` }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: C.slate400, marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                      Clinical Notes
                    </div>
                    <div style={{ fontSize: 13, color: C.slate700, whiteSpace: "pre-wrap", lineHeight: 1.6 }}>
                      {enc.notes}
                    </div>
                  </div>
                )}
              </div>
            )}
          </Card>
        );
      })}
    </div>
  );
}
