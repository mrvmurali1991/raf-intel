"use client";

import React, { useState, useMemo, useEffect } from "react";
import type { MEATEvidence } from "@/types";
import type {
  RafHistoryResponse,
  PatientSuspectsResponse,
  RecaptureGapsResponse,
  CrosswalkResult,
} from "@/lib/api";
import { lookupICD10Crosswalk } from "@/lib/api";
import {
  SectionHeader,
  EmptyState,
  ConfidencePill,
} from "@/components/healthcare-ui";
import {
  C,
  formatDate,
  rafScoreColor,
  Spinner,
  SectionLoader,
  Card,
  MeatDots,
} from "./shared";
import type {
  ExtendedRafBreakdown,
  HCCDetail,
  ScoreHistoryEntry,
  RecaptureGapItem,
  SuspectItem,
} from "./shared";

// ---------------------------------------------------------------------------
// ICD-10 Description Lookup
// ---------------------------------------------------------------------------
const ICD10_DESCRIPTIONS: Record<string, string> = {
  "I50.9": "Heart failure, unspecified",
  "I50.20": "Unspecified systolic heart failure",
  "I48.91": "Unspecified atrial fibrillation",
  "E11.9": "Type 2 diabetes mellitus without complications",
  "E11.65": "Type 2 DM with hyperglycemia",
  "N18.3": "Chronic kidney disease, stage 3",
  "N18.4": "Chronic kidney disease, stage 4",
  "J44.1": "COPD with acute exacerbation",
  "J44.9": "COPD, unspecified",
  "F33.0": "Major depressive disorder, recurrent, mild",
  "F33.1": "Major depressive disorder, recurrent, moderate",
  "M06.9": "Rheumatoid arthritis, unspecified",
  "E66.01": "Morbid obesity due to excess calories",
  "G20": "Parkinson's disease",
  "F03.90": "Unspecified dementia",
  "I73.9": "Peripheral vascular disease",
  "K74.60": "Unspecified cirrhosis of liver",
  "I63.9": "Cerebral infarction, unspecified",
  "G40.909": "Epilepsy, unspecified",
  "B20": "HIV disease",
  "I48.0": "Paroxysmal atrial fibrillation",
};

// ---------------------------------------------------------------------------
// Disease Interaction Rules (CMS-HCC V28)
// ---------------------------------------------------------------------------
const DISEASE_INTERACTIONS: Array<{ name: string; groups: number[][]; coefficient: number }> = [
  { name: "DIABETES_HF", groups: [[37, 38], [85, 86]], coefficient: 0.112 },
  { name: "HF_CHR_LUNG", groups: [[85, 86], [112, 113]], coefficient: 0.078 },
  { name: "CHF_RENAL", groups: [[85, 86], [136, 137, 138, 141]], coefficient: 0.065 },
  { name: "DIABETES_CHR_LUNG", groups: [[37, 38], [112, 113]], coefficient: 0.022 },
  { name: "HF_RENAL_DIABETES", groups: [[85, 86], [136, 137, 138, 141], [37, 38]], coefficient: 0.034 },
];

const MA_PAYMENT_PER_RAF = 11015.04;

// ---------------------------------------------------------------------------
// RAF Score Calculator Table Component
// ---------------------------------------------------------------------------
function RAFScoreCalculatorTable({ breakdown, breakdownLoading, lastCalcResult, selectedYear }: { breakdown: ExtendedRafBreakdown | undefined; breakdownLoading: boolean; lastCalcResult?: any; selectedYear: number }) {
  if (breakdownLoading) {
    return (
      <div className="animate-slide-up stagger-1">
        <SectionLoader label="Loading RAF Score Analysis..." />
      </div>
    );
  }

  if (!breakdown) {
    return (
      <div className="animate-slide-up stagger-1">
        <Card><EmptyState title="No RAF breakdown available" /></Card>
      </div>
    );
  }

  const hccDetails: HCCDetail[] = breakdown.hcc_details || [];
  const patientHccCodes = hccDetails.map((h) => Number(h.hcc_code || h.code));

  // Compute triggered interactions
  const triggeredInteractions = DISEASE_INTERACTIONS.filter((inter) =>
    inter.groups.every((group) => group.some((hcc) => patientHccCodes.includes(hcc)))
  );

  const demographicScore = breakdown.demographic_score ?? breakdown.demographic_base ?? 0;
  const diseaseScore = hccDetails.reduce((sum: number, h: HCCDetail) => sum + Number(h.coefficient || h.hcc_coefficient || 0), 0);
  const interactionScore = triggeredInteractions.reduce((sum, i) => sum + i.coefficient, 0);
  const componentSum = demographicScore + diseaseScore + interactionScore;
  const grandTotal = breakdown.final_raf ?? breakdown.raf_score ?? breakdown.total_raf ?? componentSum;

  const fmtScore = (v: number) => v.toFixed(3);
  const fmtPay = (v: number) => `$${Math.round(v).toLocaleString("en-US")}`;

  return (
    <div className="animate-slide-up stagger-1" style={{ display: "flex", flexDirection: "column", gap: 16 }}>

      {/* RAF Score + Payment */}
      <div style={{
        background: `linear-gradient(135deg, ${C.blue50} 0%, ${C.white} 100%)`,
        borderRadius: 16, border: `1px solid ${C.blue100}`,
        padding: "20px 24px", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 16,
      }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: C.slate400, marginBottom: 4 }}>Total RAF Score</div>
          <div style={{ fontSize: 36, fontWeight: 800, fontFamily: "monospace", color: C.blue600, lineHeight: 1 }}>{fmtScore(grandTotal)}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: C.slate400, marginBottom: 4 }}>Est. MA Payment</div>
          <div style={{ fontSize: 28, fontWeight: 800, fontFamily: "monospace", color: C.emerald600, lineHeight: 1 }}>{fmtPay(grandTotal * MA_PAYMENT_PER_RAF)}</div>
          <div style={{ fontSize: 12, color: C.slate400, marginTop: 6 }}>
            {["V28", breakdown.model_segment || "CNA", breakdown.measurement_year || selectedYear].map(t => (
              <span key={t} style={{ display: "inline-block", padding: "2px 8px", borderRadius: 4, fontSize: 10, fontWeight: 600, background: C.blue50, color: C.blue600, border: `1px solid ${C.blue100}`, marginLeft: 4 }}>{t}</span>
            ))}
          </div>
        </div>
      </div>

      {/* Breakdown Card */}
      <Card noPadding>
        {/* Demographic base */}
        <div style={{ padding: "14px 20px", display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: `1px solid ${C.slate100}` }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, color: C.slate700 }}>Demographic Base</div>
            <div style={{ fontSize: 11, color: C.slate400, marginTop: 1 }}>Age/sex coefficient</div>
          </div>
          <div style={{ textAlign: "right" }}>
            <span style={{ fontSize: 16, fontFamily: "monospace", fontWeight: 700, color: C.slate800 }}>{fmtScore(demographicScore)}</span>
            <span style={{ fontSize: 12, fontFamily: "monospace", color: C.emerald600, marginLeft: 12 }}>{fmtPay(demographicScore * MA_PAYMENT_PER_RAF)}</span>
          </div>
        </div>

        {/* Diagnosis section */}
        {hccDetails.length > 0 && (
          <div style={{ padding: "8px 20px 4px", fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: C.slate400 }}>
            Diagnosis ({hccDetails.length})
          </div>
        )}
        {hccDetails.map((hcc: HCCDetail, i: number) => {
          const code = hcc.hcc_code;
          const icdCodes: string[] = (hcc.icd10_codes || []).map((c: any) => typeof c === "string" ? c : c.code || "");
          const primaryIcd = icdCodes[0] || "";
          const icdDesc = primaryIcd ? (ICD10_DESCRIPTIONS[primaryIcd] || hcc.hcc_label || "") : (hcc.hcc_label || "");
          const coeff = Number(hcc.coefficient || 0);
          const meatColor = hcc.meat_status === "complete" ? C.emerald500 : hcc.meat_status === "partial" ? C.amber500 : C.slate300;
          return (
            <div key={hcc.hcc_code || hcc.code || i} style={{
              display: "flex", alignItems: "center", gap: 12, padding: "10px 20px",
              borderBottom: `1px solid ${C.slate100}`, borderLeft: `3px solid ${meatColor}`,
              marginLeft: 0, transition: "background 0.15s",
            }}
            onMouseEnter={e => (e.currentTarget.style.background = C.slate100 + "60")}
            onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
            >
              <span style={{ minWidth: 64, padding: "3px 8px", borderRadius: 6, fontSize: 12, fontWeight: 700, fontFamily: "monospace", background: C.blue50, color: C.blue600, textAlign: "center", border: `1px solid ${C.blue100}` }}>
                {primaryIcd || `HCC${code}`}
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 500, color: C.slate700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{icdDesc}</div>
                <div style={{ fontSize: 11, color: C.slate400, marginTop: 1 }}>
                  HCC {code}
                  {icdCodes.length > 1 && <span style={{ marginLeft: 6, opacity: 0.7 }}>+{icdCodes.length - 1} codes</span>}
                </div>
              </div>
              <span style={{ fontSize: 15, fontFamily: "monospace", fontWeight: 700, color: C.slate800, whiteSpace: "nowrap" }}>{fmtScore(coeff)}</span>
              <span style={{ fontSize: 13, fontFamily: "monospace", fontWeight: 600, color: C.emerald600, minWidth: 70, textAlign: "right", whiteSpace: "nowrap" }}>{fmtPay(coeff * MA_PAYMENT_PER_RAF)}</span>
            </div>
          );
        })}

        {/* Interactions */}
        <div style={{ padding: "8px 20px 4px", fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: C.slate400 }}>
          Disease Interactions ({triggeredInteractions.length})
        </div>
        {triggeredInteractions.length > 0 ? (
          triggeredInteractions.map(inter => (
            <div key={inter.name} style={{
              display: "flex", alignItems: "center", gap: 12, padding: "10px 20px",
              borderBottom: `1px solid ${C.slate100}`,
            }}>
              <span style={{ minWidth: 64, padding: "3px 8px", borderRadius: 6, fontSize: 10, fontWeight: 700, fontFamily: "monospace", background: C.amber50, color: C.amber600, textAlign: "center", border: `1px solid ${C.amber100}` }}>
                {inter.name.replace(/_/g, " ")}
              </span>
              <div style={{ flex: 1 }} />
              <span style={{ fontSize: 15, fontFamily: "monospace", fontWeight: 700, color: C.slate800 }}>{fmtScore(inter.coefficient)}</span>
              <span style={{ fontSize: 13, fontFamily: "monospace", fontWeight: 600, color: C.emerald600, minWidth: 70, textAlign: "right" }}>{fmtPay(inter.coefficient * MA_PAYMENT_PER_RAF)}</span>
            </div>
          ))
        ) : (
          <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 20px", borderBottom: `1px solid ${C.slate100}` }}>
            <span style={{ fontSize: 13, color: C.slate400 }}>No qualifying HCC combinations \u2014 interaction score is 0</span>
            <div style={{ flex: 1 }} />
            <span style={{ fontSize: 15, fontFamily: "monospace", fontWeight: 700, color: C.slate400 }}>0.000</span>
            <span style={{ fontSize: 13, fontFamily: "monospace", fontWeight: 600, color: C.slate400, minWidth: 70, textAlign: "right" }}>$0</span>
          </div>
        )}

        {/* Footer note */}
        <div style={{ padding: "8px 20px", fontSize: 10, color: C.slate400 }}>
          * Based on CMS {new Date().getFullYear()} rate of ${MA_PAYMENT_PER_RAF.toLocaleString("en-US")}/RAF point
        </div>
      </Card>

      {/* Calculation Details (collapsible) */}
      <CalcDetails breakdown={breakdown} componentSum={componentSum} grandTotal={grandTotal} lastCalcResult={lastCalcResult} />
    </div>
  );
}

function LLMInputPanel({ llmInput }: { llmInput: any }) {
  const [open, setOpen] = useState(false);
  const pill = (text: string, bg: string, fg: string, border: string) => (
    <span style={{ padding: "3px 8px", borderRadius: 5, fontSize: 11, fontFamily: "monospace", fontWeight: 600, background: bg, color: fg, border: `1px solid ${border}` }}>{text}</span>
  );
  return (
    <div style={{ borderRadius: 8, border: `1px solid ${C.purple100}`, overflow: "hidden", marginBottom: 12 }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          width: "100%", padding: "10px 14px", background: `linear-gradient(135deg, ${C.purple50}, ${C.blue50})`,
          border: "none", cursor: "pointer", display: "flex",
          justifyContent: "space-between", alignItems: "center",
          fontSize: 12, fontWeight: 600, color: C.purple600,
        }}
      >
        <span>{"\uD83D\uDCCB"} Data Sent to AI Model</span>
        <span style={{ fontSize: 14, transform: open ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.2s" }}>{"\u25BC"}</span>
      </button>
      {open && (
        <div style={{ padding: "14px 16px", fontSize: 12, background: C.white }}>
          {/* Model & Config */}
          <div style={{ display: "grid", gridTemplateColumns: "130px 1fr", gap: "5px 12px", marginBottom: 12 }}>
            <span style={{ color: C.slate400, fontWeight: 600 }}>Patient Age</span>
            <span style={{ color: C.slate700 }}>{llmInput.patient_age ?? "N/A"}</span>
            <span style={{ color: C.slate400, fontWeight: 600 }}>Patient Sex</span>
            <span style={{ color: C.slate700 }}>{llmInput.patient_sex ?? "N/A"}</span>
            <span style={{ color: C.slate400, fontWeight: 600 }}>Note Length</span>
            <span style={{ color: C.slate700 }}>{llmInput.clinical_note_chars?.toLocaleString()} characters</span>
            <span style={{ color: C.slate400, fontWeight: 600 }}>Temperature</span>
            <span style={{ fontFamily: "monospace", color: C.slate700 }}>{llmInput.temperature}</span>
          </div>

          {/* Medications */}
          {llmInput.medications?.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: C.slate500, fontWeight: 600, fontSize: 11, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.04em" }}>Medications ({llmInput.medications.length})</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {llmInput.medications.map((m: string, i: number) => <React.Fragment key={m || i}>{pill(m, C.amber50, C.amber700, C.amber100)}</React.Fragment>)}
              </div>
            </div>
          )}

          {/* Existing HCCs */}
          {llmInput.existing_hccs?.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: C.slate500, fontWeight: 600, fontSize: 11, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.04em" }}>Existing HCCs ({llmInput.existing_hccs.length})</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {llmInput.existing_hccs.map((h: string, i: number) => <React.Fragment key={h || i}>{pill(h, C.emerald50, C.emerald600, C.emerald100)}</React.Fragment>)}
              </div>
            </div>
          )}

          {/* Problem List */}
          {llmInput.problem_list?.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: C.slate500, fontWeight: 600, fontSize: 11, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.04em" }}>Problem List ({llmInput.problem_list.length})</div>
              <div style={{ fontSize: 11, color: C.slate600, lineHeight: 1.6 }}>
                {llmInput.problem_list.map((p: any, i: number) => (
                  <div key={p.diagnosis || p.title || i}>{"\u2022"} {p.title} <span style={{ fontFamily: "monospace", color: C.blue600 }}>({p.diagnosis || "no code"})</span></div>
                ))}
              </div>
            </div>
          )}

          {/* Recapture Gaps */}
          {llmInput.recapture_gaps?.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: C.slate500, fontWeight: 600, fontSize: 11, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.04em" }}>Recapture Gaps ({llmInput.recapture_gaps.length})</div>
              <div style={{ fontSize: 11, color: C.slate600, lineHeight: 1.6 }}>
                {llmInput.recapture_gaps.map((g: any, i: number) => (
                  <div key={g.diagnosis || g.title || i}>{"\u2022"} {g.title} <span style={{ fontFamily: "monospace", color: C.orange500 }}>({g.diagnosis})</span></div>
                ))}
              </div>
            </div>
          )}

          {/* Vitals */}
          {llmInput.latest_vitals && Object.keys(llmInput.latest_vitals).length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: C.slate500, fontWeight: 600, fontSize: 11, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.04em" }}>Vitals Sent</div>
              <div style={{ display: "grid", gridTemplateColumns: "100px 1fr", gap: "2px 8px", fontSize: 11, fontFamily: "monospace", color: C.slate600 }}>
                {Object.entries(llmInput.latest_vitals).map(([k, v]: [string, any]) => (
                  <React.Fragment key={k}>
                    <span style={{ color: C.slate400 }}>{k}</span>
                    <span>{String(v)}</span>
                  </React.Fragment>
                ))}
              </div>
            </div>
          )}

          {/* Med Diagnoses */}
          {llmInput.med_diagnoses?.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: C.slate500, fontWeight: 600, fontSize: 11, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.04em" }}>Medication Indications ({llmInput.med_diagnoses.length})</div>
              <div style={{ fontSize: 11, color: C.slate600, lineHeight: 1.6 }}>
                {llmInput.med_diagnoses.map((m: any, i: number) => (
                  <div key={m.drug || i}>{"\u2022"} <strong>{m.drug}</strong>: {m.note}</div>
                ))}
              </div>
            </div>
          )}

          {/* Clinical Note Preview */}
          {llmInput.clinical_note_preview && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: C.slate500, fontWeight: 600, fontSize: 11, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.04em" }}>Clinical Note Preview</div>
              <pre style={{ fontSize: 11, color: C.slate600, background: C.slate100, padding: 10, borderRadius: 6, border: `1px solid ${C.slate200}`, whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: 200, overflow: "auto", margin: 0 }}>{llmInput.clinical_note_preview}</pre>
            </div>
          )}

          {/* Extracted ICD codes */}
          {llmInput.extracted_icd_codes?.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: C.slate500, fontWeight: 600, fontSize: 11, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.04em" }}>ICD-10 Codes Extracted ({llmInput.extracted_icd_codes.length})</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {llmInput.extracted_icd_codes.map((c: string, i: number) => <React.Fragment key={c || i}>{pill(c, C.blue50, C.blue600, C.blue100)}</React.Fragment>)}
              </div>
            </div>
          )}

          {/* Tool Calls Summary */}
          {llmInput.tool_calls_summary && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: C.slate500, fontWeight: 600, fontSize: 11, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.04em" }}>AI Processing Summary</div>
              <div style={{ display: "grid", gridTemplateColumns: "160px 1fr", gap: "4px 12px", fontSize: 11, color: C.slate600 }}>
                <span style={{ color: C.slate400 }}>Total Tool Calls</span>
                <span style={{ fontWeight: 600 }}>{llmInput.tool_calls_summary.total}</span>
                <span style={{ color: C.slate400 }}>Conversation Turns</span>
                <span style={{ fontWeight: 600 }}>{llmInput.tool_calls_summary.turns}</span>
                <span style={{ color: C.slate400 }}>Processing Time</span>
                <span style={{ fontWeight: 600 }}>{llmInput.tool_calls_summary.total_time?.toFixed(1)}s</span>
                <span style={{ color: C.slate400 }}>ICD-10 Validations</span>
                <span style={{ fontWeight: 600 }}>{llmInput.tool_calls_summary.icd_validated}</span>
                <span style={{ color: C.slate400 }}>HCC Lookups</span>
                <span style={{ fontWeight: 600 }}>{llmInput.tool_calls_summary.hcc_lookups}</span>
                <span style={{ color: C.slate400 }}>Medication Checks</span>
                <span style={{ fontWeight: 600 }}>{llmInput.tool_calls_summary.med_checks}</span>
              </div>
            </div>
          )}

          {/* Reconstructed notice */}
          {llmInput._reconstructed && (
            <div style={{ fontSize: 10, color: C.slate400, fontStyle: "italic", marginTop: 6 }}>
              Partial data \u2014 click Analyze again to capture full input details (demographics, vitals, problem list, note preview).
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// Export LLMInputPanel for use in EncountersTab
export { LLMInputPanel };

function CalcDetails({ breakdown, componentSum, grandTotal, lastCalcResult }: { breakdown: ExtendedRafBreakdown; componentSum: number; grandTotal: number; lastCalcResult?: any }) {
  const [open, setOpen] = useState(false);
  const data = lastCalcResult || breakdown as any;
  const engineInput = data.engine_input || (breakdown as any)?.engine_input;
  const engineOutput = data.engine_output || (breakdown as any)?.engine_output;
  const hasEngineData = !!engineInput;

  const hccContribs: any[] = data.hcc_contributions || data.hcc_details || [];

  const stepHeader = (num: number, label: string, color: string) => (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
      <span style={{ display: "inline-block", width: 22, height: 22, borderRadius: "50%", background: color, color: C.white, textAlign: "center", lineHeight: "22px", fontSize: 11, fontWeight: 700, flexShrink: 0 }}>{num}</span>
      <span style={{ fontSize: 12, fontWeight: 700, color, textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</span>
    </div>
  );

  const pill = (text: string, bg: string, fg: string, border: string) => (
    <span style={{ padding: "3px 8px", borderRadius: 5, fontSize: 11, fontFamily: "monospace", fontWeight: 600, background: bg, color: fg, border: `1px solid ${border}` }}>{text}</span>
  );

  return (
    <div style={{ borderRadius: 12, border: `1px solid ${C.slate200}`, overflow: "hidden" }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          width: "100%", padding: "12px 20px", background: C.slate100,
          border: "none", cursor: "pointer", display: "flex",
          justifyContent: "space-between", alignItems: "center",
          fontSize: 12, fontWeight: 600, color: C.slate600,
        }}
      >
        <span>Calculation Pipeline {hasEngineData ? "(last run)" : ""}</span>
        <span style={{ fontSize: 16, transform: open ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.2s" }}>{"\u25BC"}</span>
      </button>
      {open && (
        <div style={{ padding: "20px", fontSize: 12, background: C.white }}>

          {!hasEngineData && (
            <div style={{ padding: "10px 14px", borderRadius: 8, background: C.amber50, border: `1px solid ${C.amber100}`, fontSize: 11, color: C.amber600, marginBottom: 16 }}>
              Click <strong>Calculate RAF</strong> to see the exact data sent to and received from the calculation engine.
            </div>
          )}

          {hasEngineData && (
            <>
              {/* STEP 1: Exact Engine Input */}
              {stepHeader(1, "Exact Data Sent to Calculation Engine", C.blue600)}
              <div style={{ marginLeft: 30, marginBottom: 20, padding: "14px 16px", borderRadius: 8, background: C.slate100, border: `1px solid ${C.slate200}` }}>
                <div style={{ display: "grid", gridTemplateColumns: "130px 1fr", gap: "6px 12px", fontSize: 12 }}>
                  <span style={{ color: C.slate400, fontWeight: 600 }}>Age</span>
                  <span style={{ color: C.slate700, fontWeight: 600 }}>{engineInput.age}</span>
                  <span style={{ color: C.slate400, fontWeight: 600 }}>Sex</span>
                  <span style={{ color: C.slate700, fontWeight: 600 }}>{engineInput.sex}</span>
                  <span style={{ color: C.slate400, fontWeight: 600 }}>Model Segment</span>
                  <span style={{ color: C.slate700, fontWeight: 600 }}>{engineInput.model_segment} ({engineInput.prefix_override})</span>
                  <span style={{ color: C.slate400, fontWeight: 600 }}>MACI Factor</span>
                  <span style={{ fontFamily: "monospace", color: C.slate700 }}>{engineInput.maci}</span>
                  <span style={{ color: C.slate400, fontWeight: 600 }}>Norm Factor</span>
                  <span style={{ fontFamily: "monospace", color: C.slate700 }}>{engineInput.norm_factor}</span>
                </div>
                <div style={{ marginTop: 10, borderTop: `1px solid ${C.slate200}`, paddingTop: 10 }}>
                  <div style={{ color: C.slate400, fontWeight: 600, marginBottom: 6 }}>ICD-10 Codes Sent ({engineInput.icd_codes?.length || 0})</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                    {(engineInput.icd_codes || []).map((c: string, i: number) => <React.Fragment key={c || i}>{pill(c, C.blue50, C.blue600, C.blue100)}</React.Fragment>)}
                  </div>
                  <div style={{ fontSize: 10, color: C.slate400, marginTop: 6 }}>
                    Collected from: OpenEMR billing codes + AI encounter analysis + document analysis + manual entries
                  </div>
                </div>
              </div>

              {/* STEP 2: Exact Engine Output */}
              {stepHeader(2, "Exact Data Received from Engine", C.emerald600)}
              <div style={{ marginLeft: 30, marginBottom: 20, padding: "14px 16px", borderRadius: 8, background: C.emerald50, border: `1px solid ${C.emerald100}` }}>
                <div style={{ display: "grid", gridTemplateColumns: "130px 1fr", gap: "6px 12px", fontSize: 12 }}>
                  <span style={{ color: C.slate400, fontWeight: 600 }}>Raw Score</span>
                  <span style={{ fontFamily: "monospace", fontWeight: 700, color: C.slate700 }}>{engineOutput.risk_score_raw}</span>
                  <span style={{ color: C.slate400, fontWeight: 600 }}>Payment Score</span>
                  <span style={{ fontFamily: "monospace", fontWeight: 700, color: C.blue600 }}>{engineOutput.risk_score_payment?.toFixed(3)}</span>
                  <span style={{ color: C.slate400, fontWeight: 600 }}>Demographics</span>
                  <span style={{ fontFamily: "monospace", color: C.slate700 }}>{engineOutput.risk_score_demographics}</span>
                </div>
                <div style={{ marginTop: 10, borderTop: `1px solid ${C.emerald100}`, paddingTop: 10 }}>
                  <div style={{ color: C.slate400, fontWeight: 600, marginBottom: 6 }}>HCCs Mapped ({engineOutput.hcc_list?.length || 0})</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 8 }}>
                    {(engineOutput.hcc_list || []).map((h: string, i: number) => <React.Fragment key={h || i}>{pill(`HCC ${h}`, C.emerald50, C.emerald600, C.emerald100)}</React.Fragment>)}
                  </div>
                  {(engineOutput.hcc_details || []).map((h: any, i: number) => (
                    <div key={h.hcc || `hcc-detail-${i}`} style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0", fontSize: 11, borderBottom: `1px solid ${C.emerald100}` }}>
                      <span style={{ fontFamily: "monospace", fontWeight: 700, color: C.emerald600, minWidth: 55 }}>HCC {h.hcc}</span>
                      <span style={{ flex: 1, color: C.slate600 }}>{h.label}</span>
                      <span style={{ fontFamily: "monospace", fontWeight: 600, color: C.slate700 }}>{h.coefficient?.toFixed(3)}</span>
                    </div>
                  ))}
                </div>
                {engineOutput.all_coefficients && Object.keys(engineOutput.all_coefficients).length > 0 && (
                  <div style={{ marginTop: 10, borderTop: `1px solid ${C.emerald100}`, paddingTop: 10 }}>
                    <div style={{ color: C.slate400, fontWeight: 600, marginBottom: 6 }}>All Coefficients</div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 80px", gap: "2px 8px", fontSize: 11, fontFamily: "monospace" }}>
                      {Object.entries(engineOutput?.all_coefficients || {}).sort((a: any, b: any) => b[1] - a[1]).map(([k, v]: [string, any]) => (
                        <React.Fragment key={k}>
                          <span style={{ color: C.slate600 }}>{k}</span>
                          <span style={{ textAlign: "right", fontWeight: 600, color: C.slate700 }}>{v.toFixed(3)}</span>
                        </React.Fragment>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </>
          )}

          {/* Always show ICD -> HCC mapping from breakdown */}
          {!hasEngineData && (
            <>
              {stepHeader(1, `ICD-10 to HCC Mapping (${hccContribs.length} HCCs)`, C.emerald600)}
              <div style={{ marginLeft: 30, marginBottom: 16, borderRadius: 8, border: `1px solid ${C.slate200}`, overflow: "hidden" }}>
                {hccContribs.map((h: any, i: number) => {
                  const hccCode = h.hcc_code || h.code;
                  const icds: string[] = (h.icd10_codes || []).map((c: any) => typeof c === "string" ? c : c.code || "");
                  return (
                    <div key={h.hcc_code || h.code || i} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 12px", borderBottom: i < hccContribs.length - 1 ? `1px solid ${C.slate100}` : "none", fontSize: 11 }}>
                      <span style={{ fontFamily: "monospace", color: C.emerald600, fontWeight: 700, minWidth: 55 }}>HCC {hccCode}</span>
                      <span style={{ color: C.slate400 }}>{"\u2190"}</span>
                      <div style={{ display: "flex", gap: 3, flexWrap: "wrap" }}>
                        {icds.length > 0 ? icds.map(c => (
                          <span key={c} style={{ padding: "1px 5px", borderRadius: 3, fontFamily: "monospace", fontSize: 10, background: C.blue50, color: C.blue600 }}>{c}</span>
                        )) : <span style={{ color: C.slate400 }}>-</span>}
                      </div>
                      <span style={{ marginLeft: "auto", fontFamily: "monospace", fontWeight: 600, color: C.slate700 }}>{(h.coefficient || 0).toFixed(3)}</span>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function PatientCrosswalk({ breakdown, rafScore, suspects }: { breakdown: ExtendedRafBreakdown | undefined; rafScore: number | null; suspects: PatientSuspectsResponse | undefined }) {
  const [extraCodes, setExtraCodes] = useState("");
  const [results, setResults] = useState<CrosswalkResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);

  const currentRaf = rafScore ?? (breakdown?.demographic_score ?? 0) + (breakdown?.disease_score ?? 0) + (breakdown?.interaction_score ?? 0);

  const patientCodes = useMemo(() => {
    if (!breakdown?.hcc_details) return [];
    const codes: string[] = [];
    for (const hcc of breakdown.hcc_details) {
      for (const c of (hcc.icd10_codes || [])) {
        const code = typeof c === "string" ? c : c.code || "";
        if (code && !codes.includes(code)) codes.push(code);
      }
    }
    return codes;
  }, [breakdown]);

  const suspectSuggestions = useMemo(() => {
    const list = suspects?.suspects || suspects || [];
    if (!Array.isArray(list)) return [];
    const seen = new Set(patientCodes.map(c => c.replace(/\./g, "").toUpperCase()));
    return list
      .filter((s: SuspectItem) => {
        const code = (s.suspect_icd10 || s.icd10_code || s.icd10 || "").replace(/\./g, "").toUpperCase();
        return code && !seen.has(code) && (s.status === "open" || !s.status);
      })
      .map((s: SuspectItem) => ({
        code: s.suspect_icd10 || s.icd10_code || s.icd10 || "",
        hcc: s.suspect_hcc || s.hcc_code || "",
        confidence: s.confidence_score || s.confidence || 0,
        coefficient: s.hcc_coefficient || 0,
        rationale: s.rationale || s.evidence_detail || "",
      }));
  }, [suspects, patientCodes]);

  const allCodes = useMemo(() => {
    const extra = extraCodes.split(/[,\s]+/).map(c => c.trim().toUpperCase()).filter(Boolean);
    const combined = [...patientCodes];
    for (const c of extra) if (!combined.includes(c)) combined.push(c);
    return combined;
  }, [patientCodes, extraCodes]);

  const handleLookup = async () => {
    if (allCodes.length === 0) return;
    setLoading(true);
    setHasSearched(true);
    try {
      const data = await lookupICD10Crosswalk(allCodes);
      setResults(data.results || []);
    } catch { setResults([]); }
    finally { setLoading(false); }
  };

  useEffect(() => {
    if (patientCodes.length > 0 && !hasSearched) handleLookup();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patientCodes]);

  const isExtra = (code: string) => {
    const n = code.replace(/\./g, "").toUpperCase();
    return !patientCodes.some(pc => pc.replace(/\./g, "").toUpperCase() === n);
  };

  const addSuggestion = (code: string) => {
    const current = extraCodes.split(/[,\s]+/).map(c => c.trim()).filter(Boolean);
    if (!current.some(c => c.toUpperCase() === code.toUpperCase())) {
      setExtraCodes([...current, code].join(", "));
    }
  };

  const extraCoeffSum = useMemo(() => {
    if (!results.length) return 0;
    return results
      .filter(r => isExtra(r.icd10_code) && r.cms_hcc_v28)
      .reduce((sum, r) => {
        const match = suspectSuggestions.find((s) =>
          s.code.replace(/\./g, "").toUpperCase() === r.icd10_code.replace(/\./g, "").toUpperCase()
        );
        return sum + (match?.coefficient || 0.15);
      }, 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [results, suspectSuggestions]);

  const projectedRaf = currentRaf + extraCoeffSum;
  const hasExtras = results.some(r => isExtra(r.icd10_code));

  return (
    <div className="animate-slide-up stagger-2" style={{ display: "flex", flexDirection: "column", gap: 16 }}>

      {/* RAF Impact Preview */}
      {hasExtras && extraCoeffSum > 0 && (
        <div style={{
          display: "grid", gridTemplateColumns: "1fr auto 1fr", alignItems: "center", gap: 16,
          padding: "16px 24px", borderRadius: 12,
          background: `linear-gradient(135deg, ${C.blue50} 0%, ${C.emerald50} 100%)`,
          border: `1px solid ${C.blue100}`,
        }}>
          <div>
            <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: C.slate400 }}>Current RAF</div>
            <div style={{ fontSize: 24, fontWeight: 800, fontFamily: "monospace", color: C.slate700 }}>{currentRaf.toFixed(3)}</div>
            <div style={{ fontSize: 12, color: C.slate400 }}>${Math.round(currentRaf * MA_PAYMENT_PER_RAF).toLocaleString()}/yr</div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
            <span style={{ fontSize: 20, color: C.blue600 }}>{"\u2192"}</span>
            <span style={{ fontSize: 12, fontWeight: 700, fontFamily: "monospace", color: C.emerald600, background: C.emerald50, padding: "2px 8px", borderRadius: 6, border: `1px solid ${C.emerald100}` }}>
              +{extraCoeffSum.toFixed(3)}
            </span>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: C.emerald600 }}>Projected RAF</div>
            <div style={{ fontSize: 24, fontWeight: 800, fontFamily: "monospace", color: C.emerald600 }}>{projectedRaf.toFixed(3)}</div>
            <div style={{ fontSize: 12, color: C.emerald600 }}>
              ${Math.round(projectedRaf * MA_PAYMENT_PER_RAF).toLocaleString()}/yr
              <span style={{ fontWeight: 700, marginLeft: 4 }}>(+${Math.round(extraCoeffSum * MA_PAYMENT_PER_RAF).toLocaleString()})</span>
            </div>
          </div>
        </div>
      )}

      {/* Main Crosswalk Card */}
      <Card noPadding>
        <div style={{ padding: "16px 20px", borderBottom: `1px solid ${C.slate100}` }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
            <div>
              <div style={{ fontSize: 15, fontWeight: 700, color: C.slate800 }}>ICD-10 to HCC Crosswalk</div>
              <div style={{ fontSize: 12, color: C.slate400, marginTop: 2 }}>{patientCodes.length} active codes {hasExtras && `+ ${results.filter(r => isExtra(r.icd10_code)).length} what-if`}</div>
            </div>
          </div>
          {/* Input */}
          <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "center" }}>
            <input
              value={extraCodes}
              onChange={e => setExtraCodes(e.target.value)}
              placeholder="Add codes to test... e.g. N18.4, J44.1"
              style={{
                flex: 1, padding: "8px 12px", borderRadius: 8, border: `1px solid ${C.slate200}`,
                fontSize: 13, fontFamily: "monospace", color: C.slate800, outline: "none",
                transition: "border-color 0.15s",
              }}
              onFocus={e => (e.target.style.borderColor = C.blue600)}
              onBlur={e => (e.target.style.borderColor = C.slate200)}
              onKeyDown={e => e.key === "Enter" && handleLookup()}
            />
            <button
              onClick={handleLookup}
              disabled={loading || allCodes.length === 0}
              style={{
                padding: "8px 16px", borderRadius: 8, border: "none",
                background: C.blue600, color: C.white, fontSize: 13, fontWeight: 600,
                cursor: loading ? "wait" : "pointer", opacity: loading ? 0.7 : 1,
                whiteSpace: "nowrap",
              }}
            >
              {loading ? "Looking up..." : "Look Up"}
            </button>
          </div>
        </div>

        {/* Results table */}
        {hasSearched && results.length > 0 && (
          <>
            <div style={{
              display: "grid", gridTemplateColumns: "36px minmax(70px,1fr) 70px 70px 70px 2.5fr",
              padding: "8px 20px", gap: 4, borderBottom: `1px solid ${C.slate200}`, background: "#f0fdfa",
            }}>
              {["#", "ICD-10", "V24", "V28", "RxHCC", "Description"].map((h, i) => (
                <span key={h} style={{
                  fontSize: 10, fontWeight: 700, textTransform: "uppercase" as const,
                  letterSpacing: "0.06em", color: C.blue600,
                  textAlign: i === 0 ? "center" as const : "left" as const,
                }}>{h}</span>
              ))}
            </div>
            {results.map((r: CrosswalkResult, i: number) => {
              const extra = isExtra(r.icd10_code);
              return (
                <div key={r.icd10_code || i} style={{
                  display: "grid", gridTemplateColumns: "36px minmax(70px,1fr) 70px 70px 70px 2.5fr",
                  padding: "9px 20px", gap: 4, alignItems: "center",
                  borderBottom: `1px solid ${C.slate100}`,
                  borderLeft: extra ? `3px solid ${C.amber500}` : `3px solid transparent`,
                  background: extra ? C.amber50 + "40" : "transparent",
                  transition: "background 0.15s",
                }}
                onMouseEnter={e => (e.currentTarget.style.background = C.slate100 + "60")}
                onMouseLeave={e => (e.currentTarget.style.background = extra ? C.amber50 + "40" : "transparent")}
                >
                  <span style={{ fontSize: 12, color: C.slate400, textAlign: "center", fontWeight: 600 }}>{r.sno}</span>
                  <span style={{ fontSize: 13, fontFamily: "monospace", fontWeight: 700, color: extra ? C.amber600 : C.blue600 }}>{r.icd10_code}</span>
                  <span style={{ fontSize: 12, fontFamily: "monospace", fontWeight: 600, color: r.cms_hcc_v24 ? C.slate700 : C.slate300 }}>{r.cms_hcc_v24 ?? "--"}</span>
                  <span style={{ fontSize: 12, fontFamily: "monospace", fontWeight: 600, color: r.cms_hcc_v28 ? C.slate700 : C.slate300 }}>{r.cms_hcc_v28 ?? "--"}</span>
                  <span style={{ fontSize: 12, fontFamily: "monospace", fontWeight: 600, color: r.rxhcc ? C.slate700 : C.slate300 }}>{r.rxhcc ?? "--"}</span>
                  <span style={{ fontSize: 12, color: C.slate600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {r.description || ""}
                    {extra && <span style={{ marginLeft: 6, fontSize: 10, padding: "1px 5px", borderRadius: 4, background: C.amber100, color: C.amber600, fontWeight: 600 }}>What-if</span>}
                  </span>
                </div>
              );
            })}
          </>
        )}
        {hasSearched && !results.length && !loading && <EmptyState title="No crosswalk results found" />}
      </Card>

      {/* Smart Suggestions */}
      {suspectSuggestions.length > 0 && (
        <Card noPadding>
          <div style={{ padding: "14px 20px", borderBottom: `1px solid ${C.slate100}` }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: C.slate800 }}>Codes to Consider</div>
            <div style={{ fontSize: 12, color: C.slate400, marginTop: 1 }}>AI-detected conditions not yet coded \u2014 click to add to what-if analysis</div>
          </div>
          {suspectSuggestions.map((s, i: number) => {
            const alreadyAdded = extraCodes.toUpperCase().includes(s.code.replace(/\./g, "").toUpperCase()) ||
                                 extraCodes.includes(s.code);
            return (
              <div key={s.code || i} style={{
                display: "flex", alignItems: "center", gap: 12, padding: "10px 20px",
                borderBottom: `1px solid ${C.slate100}`, transition: "background 0.15s",
              }}
              onMouseEnter={e => (e.currentTarget.style.background = C.slate100 + "60")}
              onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
              >
                <span style={{ minWidth: 64, padding: "3px 8px", borderRadius: 6, fontSize: 12, fontWeight: 700, fontFamily: "monospace", background: C.amber50, color: C.amber600, textAlign: "center", border: `1px solid ${C.amber100}` }}>
                  {s.code}
                </span>
                <span style={{ fontSize: 11, fontFamily: "monospace", fontWeight: 600, color: C.slate400, minWidth: 50 }}>
                  HCC {s.hcc}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, color: C.slate600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.rationale}</div>
                </div>
                <span style={{
                  fontSize: 11, fontWeight: 700, fontFamily: "monospace", padding: "2px 6px", borderRadius: 4,
                  background: s.confidence >= 0.8 ? C.emerald50 : C.amber50,
                  color: s.confidence >= 0.8 ? C.emerald600 : C.amber600,
                  border: `1px solid ${s.confidence >= 0.8 ? C.emerald100 : C.amber100}`,
                }}>
                  {Math.round(s.confidence * 100)}%
                </span>
                {s.coefficient > 0 && (
                  <span style={{ fontSize: 12, fontFamily: "monospace", fontWeight: 600, color: C.emerald600, minWidth: 50, textAlign: "right" }}>
                    +{s.coefficient.toFixed(3)}
                  </span>
                )}
                <button
                  onClick={() => addSuggestion(s.code)}
                  disabled={alreadyAdded}
                  style={{
                    padding: "4px 10px", borderRadius: 6, border: `1px solid ${alreadyAdded ? C.slate200 : C.blue100}`,
                    background: alreadyAdded ? C.slate100 : C.blue50, color: alreadyAdded ? C.slate400 : C.blue600,
                    fontSize: 11, fontWeight: 600, cursor: alreadyAdded ? "default" : "pointer",
                    whiteSpace: "nowrap",
                  }}
                >
                  {alreadyAdded ? "Added" : "Add"}
                </button>
              </div>
            );
          })}
        </Card>
      )}
    </div>
  );
}

function RAFHistoryBars({ history }: { history: RafHistoryResponse | ScoreHistoryEntry[] | undefined }) {
  const scores: ScoreHistoryEntry[] | undefined = Array.isArray(history) ? history : (history as RafHistoryResponse | undefined)?.scores ?? (history as RafHistoryResponse | undefined)?.history;
  if (!scores || !Array.isArray(scores) || scores.length === 0) {
    return <EmptyState title="No historical scores available" />;
  }

  const maxScore = Math.max(
    ...scores.map((s: ScoreHistoryEntry) => s.raf_score || s.score || 0),
    1
  );

  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-end",
        gap: 16,
        height: 160,
        padding: "0 8px",
      }}
    >
      {scores.map((entry: ScoreHistoryEntry, i: number) => {
        const score = entry.raf_score || entry.score || 0;
        const year = entry.year || entry.measurement_year;
        const heightPct = Math.max((score / maxScore) * 100, 8);
        const color = rafScoreColor(score);

        return (
          <div
            key={entry.measurement_year || entry.year || i}
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 6,
              flex: 1,
            }}
          >
            <span
              className="tabular-nums"
              style={{
                fontSize: 12,
                fontWeight: 700,
                fontFamily: "monospace",
                color,
              }}
            >
              {(score ?? 0).toFixed(3)}
            </span>
            <div
              style={{
                width: "100%",
                maxWidth: 48,
                height: `${heightPct}%`,
                minHeight: 8,
                borderRadius: "6px 6px 0 0",
                background: `${color}22`,
                border: `2px solid ${color}`,
                borderBottom: "none",
                transition: "height 0.4s ease",
              }}
            />
            <span
              style={{
                fontSize: 12,
                fontWeight: 600,
                color: C.slate500,
              }}
            >
              {year}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function RAFTab({
  breakdown,
  breakdownLoading,
  history,
  historyLoading,
  recapture,
  recaptureLoading,
  rafScore,
  suspects,
  lastCalcResult,
  selectedYear,
}: {
  breakdown: ExtendedRafBreakdown | undefined;
  breakdownLoading: boolean;
  history: RafHistoryResponse | undefined;
  historyLoading: boolean;
  recapture: RecaptureGapsResponse | RecaptureGapItem[] | undefined;
  recaptureLoading: boolean;
  rafScore: number | null;
  suspects: PatientSuspectsResponse | undefined;
  lastCalcResult?: any;
  selectedYear: number;
}) {
  const recaptureItems: RecaptureGapItem[] = (() => {
    if (Array.isArray(recapture)) return recapture;
    const r = recapture as any;
    const raw = r?.gaps ?? r?.recapture_gaps ?? [];
    return raw.map((g: any) => ({
      ...g,
      description: g.description || g.title || "",
      icd10_code: g.icd10_code || (g.diagnosis?.includes(":") ? g.diagnosis.split(":").pop()?.trim() : g.diagnosis) || "",
    }));
  })();
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <RAFScoreCalculatorTable breakdown={breakdown} breakdownLoading={breakdownLoading} lastCalcResult={lastCalcResult} selectedYear={selectedYear} />
      <PatientCrosswalk breakdown={breakdown} rafScore={rafScore} suspects={suspects} />
      <Card className="animate-slide-up stagger-3 hover-lift">
        <SectionHeader title="Score History" />
        {historyLoading ? (
          <SectionLoader />
        ) : (
          <RAFHistoryBars history={history} />
        )}
      </Card>
      <Card noPadding className="animate-slide-up stagger-4 hover-lift">
        <SectionHeader title="Recapture Gaps" />
        {recaptureLoading ? (
          <SectionLoader />
        ) : !recaptureItems.length ? (
          <EmptyState title="No recapture gaps identified" />
        ) : (
          <div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 100px 100px 100px",
                padding: "8px 20px",
                background: C.slate100,
                borderTop: `1px solid ${C.slate200}`,
                borderBottom: `1px solid ${C.slate200}`,
              }}
            >
              {["Condition", "HCC", "Last Year", "Coefficient"].map((h) => (
                <span
                  key={h}
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                    color: C.slate400,
                  }}
                >
                  {h}
                </span>
              ))}
            </div>
            {recaptureItems.map(
              (gap: RecaptureGapItem, i: number) => (
                <div
                  key={gap.hcc_code || gap.icd10_code || gap.hcc || `gap-${i}`}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr 100px 100px 100px",
                    padding: "10px 20px",
                    borderBottom: `1px solid ${C.slate100}`,
                    background: i % 2 === 1 ? C.slate100 + "60" : "transparent",
                    transition: "background 0.15s",
                  }}
                  onMouseEnter={(e) =>
                    (e.currentTarget.style.background = C.slate100)
                  }
                  onMouseLeave={(e) =>
                    (e.currentTarget.style.background = i % 2 === 1 ? C.slate100 + "60" : "transparent")
                  }
                >
                  <span
                    style={{
                      fontSize: 13,
                      fontWeight: 500,
                      color: C.slate800,
                    }}
                  >
                    {gap.condition ||
                      gap.hcc_label ||
                      gap.description ||
                      "\u2014"}
                  </span>
                  <span>
                    <span
                      style={{
                        display: "inline-block",
                        padding: "2px 8px",
                        borderRadius: 4,
                        fontSize: 11,
                        fontWeight: 600,
                        fontFamily: "monospace",
                        background: C.slate100,
                        color: C.slate700,
                        border: `1px solid ${C.slate200}`,
                      }}
                    >
                      {gap.hcc_code || gap.hcc || "\u2014"}
                    </span>
                  </span>
                  <span style={{ fontSize: 13, color: C.slate500 }}>
                    {gap.prior_year || gap.last_captured_year || "\u2014"}
                  </span>
                  <span
                    style={{
                      fontSize: 13,
                      fontFamily: "monospace",
                      fontWeight: 600,
                      color: C.blue600,
                    }}
                  >
                    {gap.coefficient != null
                      ? `+${Number(gap.coefficient).toFixed(3)}`
                      : "\u2014"}
                  </span>
                </div>
              )
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
