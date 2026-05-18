"use client";

import React from "react";
import { ClinicalHighlightsPanel } from "./ClinicalHighlightsPanel";
import type { Patient, MEATEvidence, AIDiagnosis } from "@/types";
import type {
  PatientProfile,
  PatientEncountersResponse,
  ProblemListResponse,
  RecaptureGapsResponse,
  MedicationsResponse,
  ClinicalFindingsResponse,
} from "@/lib/api";
import {
  RiskGauge,
  SectionHeader,
  EmptyState,
  DataRow,
  ProgressBar,
} from "@/components/healthcare-ui";
import { calculateAge } from "@/lib/utils";
import {
  C,
  formatDate,
  rafScoreColor,
  Spinner,
  SectionLoader,
  Card,
  MeatDots,
  SkeletonRows,
  SkeletonDataRows,
  SkeletonChecklist,
  PanelWithTimeout,
  WithTooltip,
} from "./shared";
import type {
  ExtendedRafBreakdown,
  EncounterItem,
  ProblemItem,
  RecaptureGapItem,
} from "./shared";

function DataCompletenessChecklist({ profile, encounters, problems, meds, labSuspects, vitalsSuspects, selectedYear }: {
  profile: PatientProfile | undefined;
  encounters?: PatientEncountersResponse | EncounterItem[];
  problems?: ProblemListResponse | ProblemItem[];
  meds?: MedicationsResponse | Array<{ drug?: string }>;
  labSuspects?: ClinicalFindingsResponse | Array<unknown>;
  vitalsSuspects?: ClinicalFindingsResponse | Array<unknown>;
  selectedYear: number;
}) {
  // Build completeness from year-filtered query data instead of all-time profile
  const encList: EncounterItem[] = Array.isArray(encounters) ? encounters : ((encounters as PatientEncountersResponse | undefined)?.encounters ?? []);
  const probList: ProblemItem[] = Array.isArray(problems) ? problems : ((problems as ProblemListResponse | undefined)?.problems ?? []);
  const medList = Array.isArray(meds) ? meds : ((meds as MedicationsResponse | undefined)?.medications ?? []);
  const hasEncounters = encList.length > 0;
  const hasNotes = encList.some((e: EncounterItem) => e.notes || e.has_notes);
  const hasProblems = probList.length > 0;
  const hasMeds = medList.length > 0;
  const hasVitals = !!(profile?.vitals?.latest) || (Array.isArray(vitalsSuspects) ? vitalsSuspects.length > 0 : !!(vitalsSuspects?.suspects?.length));
  const hasLabs = !!(((profile?.labs as { results?: unknown[] } | undefined))?.results?.length) || (Array.isArray(labSuspects) ? labSuspects.length > 0 : !!(labSuspects?.suspects?.length));
  // These are not year-specific — use profile
  const hasInsurance = !!(profile?.enrollment) && profile.enrollment?.source !== "default";
  const hasImmunizations = Array.isArray(profile?.immunizations) && profile.immunizations.length > 0;
  const hasBilling = !!(profile?.billing?.icd10_codes?.length);
  const hasDemographics = !!(profile?.demographics?.race) && !!(profile?.demographics?.language);

  const sections = [
    { label: "Encounters", present: hasEncounters },
    { label: "Clinical Notes", present: hasNotes },
    { label: "Problems", present: hasProblems },
    { label: "Medications", present: hasMeds },
    { label: "Vitals", present: hasVitals },
    { label: "Labs", present: hasLabs },
    { label: "Billing", present: hasBilling },
    { label: "Insurance", present: hasInsurance },
    { label: "Immunizations", present: hasImmunizations },
    { label: "Demographics", present: hasDemographics },
  ];

  const pct = sections.length > 0
    ? Math.round((sections.filter((s) => s.present).length / sections.length) * 100)
    : 0;

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <ProgressBar
          value={pct}
          label="Overall"
          color={pct >= 80 ? C.emerald500 : pct >= 50 ? C.amber500 : C.red500}
          height={6}
        />
      </div>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        {sections.map((s) => (
          <div
            key={s.label}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              fontSize: 13,
            }}
          >
            <span
              className="text-muted-foreground"
            style={{
                textTransform: "capitalize",
              }}
            >
              {s.label}
            </span>
            {s.present ? (
              <span
                className="text-emerald-600 dark:text-emerald-400"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 4,
                  fontSize: 12,
                  fontWeight: 600,
                }}
              >
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="3"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <polyline points="20 6 9 17 4 12" />
                </svg>
                Available
              </span>
            ) : (
              <span
                className="text-red-500 dark:text-red-400"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 4,
                  fontSize: 12,
                  fontWeight: 500,
                }}
              >
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="3"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
                Missing
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export function OverviewTab({
  pid,
  patient,
  profile,
  profileLoading,
  breakdown,
  breakdownLoading,
  problems,
  problemsLoading,
  encounters,
  encountersLoading,
  recapture,
  recaptureLoading,
  dob,
  sex,
  rafScore,
  analyzeMutation,
  setActiveTab,
  aiAnalysis,
  selectedYear,
  meds,
  labSuspects,
  vitalsSuspects,
  onRetryProblems,
  onRetryEncounters,
  onRetryRecapture,
  onRetryProfile,
}: {
  pid: string;
  patient: Patient | undefined;
  profile: PatientProfile | undefined;
  profileLoading: boolean;
  breakdown: ExtendedRafBreakdown | undefined;
  breakdownLoading: boolean;
  problems: ProblemListResponse | ProblemItem[] | undefined;
  problemsLoading: boolean;
  encounters: PatientEncountersResponse | undefined;
  encountersLoading: boolean;
  recapture: RecaptureGapsResponse | RecaptureGapItem[] | undefined;
  recaptureLoading: boolean;
  dob: string;
  sex: string;
  rafScore: number | null;
  analyzeMutation: { mutate: (encId: number) => void; isPending: boolean; variables?: number };
  setActiveTab: (tab: string) => void;
  aiAnalysis: {
    totalDx: number;
    hccDx: number;
    analyzedEncounters: number;
    totalEncounters: number;
    diagnoses: AIDiagnosis[];
    aiOnlyCodes: AIDiagnosis[];
    aiOnlyCount: number;
  } | null;
  selectedYear: number;
  meds?: MedicationsResponse | Array<{ drug?: string }>;
  labSuspects?: ClinicalFindingsResponse | Array<unknown>;
  vitalsSuspects?: ClinicalFindingsResponse | Array<unknown>;
  onRetryProblems?: () => void;
  onRetryEncounters?: () => void;
  onRetryRecapture?: () => void;
  onRetryProfile?: () => void;
}) {
  const encountersWithNotes = (encounters?.encounters || []).filter(
    (e: EncounterItem) => !!e.notes || !!e.has_notes
  );
  const hasEncountersWithNotes = encountersWithNotes.length > 0;
  const hccCount = breakdown?.hcc_count ?? breakdown?.hcc_details?.length ?? 0;
  const isDemoOnly = hccCount === 0;
  const patientAge = dob ? calculateAge(dob) : null;
  const patientSex = sex === "Female" ? "Female" : sex === "Male" ? "Male" : sex;
  const problemItems: ProblemItem[] = Array.isArray(problems) ? problems : (problems as ProblemListResponse | undefined)?.problems ?? [];
  const recaptureItems: RecaptureGapItem[] = (() => {
    if (Array.isArray(recapture)) return recapture;
    const r = recapture as Partial<{ gaps: RecaptureGapItem[]; recapture_gaps: RecaptureGapItem[] }>;
    const raw = r?.gaps ?? r?.recapture_gaps ?? [];
    return raw.map((g: RecaptureGapItem) => ({
      ...g,
      description: g.description || g.label || "",
      icd10_code: g.icd10_code || "",
    }));
  })();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* Analysis Status Banner */}
      {isDemoOnly && (
        <div className="animate-slide-up stagger-1 bg-amber-50 border border-amber-200 dark:bg-amber-950 dark:border-amber-700" style={{
          borderRadius: 10,
          padding: "16px 20px",
          display: "flex",
          alignItems: "center",
          gap: 16,
        }}>
          <div className="bg-amber-100 dark:bg-amber-900" style={{
            width: 44, height: 44, borderRadius: 10,
            display: "flex", alignItems: "center", justifyContent: "center",
            flexShrink: 0,
          }}>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#D97706" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
              <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
          </div>
          <div style={{ flex: 1 }}>
            <div className="text-sm font-bold text-amber-800 dark:text-amber-200" style={{ marginBottom: 2 }}>
              Demographics-Only Score
            </div>
            <div className="text-sm text-amber-700 dark:text-amber-300" style={{ lineHeight: 1.5 }}>
              This RAF score ({rafScore != null ? Number(rafScore).toFixed(3) : "\u2014"}) is calculated from demographics only
              ({patientAge ? `${patientAge}-year-old` : ""} {patientSex || ""}).
              {hasEncountersWithNotes
                ? " Run analysis on clinical encounters to identify HCC conditions and calculate the full risk-adjusted score."
                : " No encounters with clinical notes found \u2014 the pipeline needs clinical notes to extract diagnoses."}
            </div>
          </div>
          {hasEncountersWithNotes && (
            <button
              onClick={() => setActiveTab("encounters")}
              className="bg-amber-600 text-white hover:bg-amber-700"
              style={{
                padding: "10px 18px", borderRadius: 8, border: "none",
                fontSize: 13, fontWeight: 700,
                cursor: "pointer", whiteSpace: "nowrap", flexShrink: 0,
              }}
            >
              Go to Encounters \u2192
            </button>
          )}
        </div>
      )}

      {!isDemoOnly && (
        <div className="animate-slide-up stagger-1 bg-emerald-50 border border-emerald-200 dark:bg-emerald-950 dark:border-emerald-700" style={{
          borderRadius: 10,
          padding: "14px 20px",
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#059669" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" />
          </svg>
          <div className="text-sm font-medium text-emerald-800 dark:text-emerald-200">
            <strong>{hccCount} HCC condition{hccCount !== 1 ? "s" : ""}</strong> identified from clinical analysis.
            RAF score includes demographic ({Number(breakdown?.demographic_score || 0).toFixed(3)}) + disease ({Number(breakdown?.disease_score || 0).toFixed(3)})
            {(breakdown?.interaction_score ?? 0) > 0 ? ` + interactions (${Number(breakdown?.interaction_score).toFixed(3)})` : ""}.
          </div>
        </div>
      )}

      {/* AI Analysis Summary */}
      {aiAnalysis && aiAnalysis.totalDx > 0 && (
        <div className="animate-fade-in" style={{
          background: "linear-gradient(135deg, #EFF6FF, #F0FDF4)",
          borderRadius: 10,
          border: `1px solid ${C.blue100}`,
          padding: "16px 20px",
          marginBottom: 16,
        }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 18 }}>{"\uD83E\uDD16"}</span>
              <span className="text-sm font-bold text-foreground">
                AI Analysis Summary
              </span>
              <span className="bg-emerald-50 text-emerald-600 border border-emerald-100 dark:bg-emerald-950 dark:text-emerald-400 dark:border-emerald-800" style={{
                padding: "2px 8px", borderRadius: 999, fontSize: 10, fontWeight: 700,
              }}>
                {aiAnalysis.analyzedEncounters}/{aiAnalysis.totalEncounters} encounters analyzed
              </span>
            </div>
            <span className="text-xs text-muted-foreground">
              Powered by AI Engine
            </span>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
            {/* Total AI Diagnoses */}
            <div style={{
              background: "hsl(var(--card))", borderRadius: 8, padding: "12px 16px",
              border: `1px solid ${C.slate200}`,
            }}>
              <div className="text-muted-foreground" style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
                AI-Extracted Diagnoses
              </div>
              <div className="text-primary font-mono" style={{ fontSize: 22, fontWeight: 800 }}>
                {aiAnalysis.totalDx}
              </div>
              <div className="text-muted-foreground" style={{ fontSize: 11, marginTop: 2 }}>
                {aiAnalysis.hccDx} with HCC mapping
              </div>
            </div>

            {/* New codes not in billing */}
            <div style={{
              background: "hsl(var(--card))", borderRadius: 8, padding: "12px 16px",
              border: `1px solid ${aiAnalysis.aiOnlyCount > 0 ? C.emerald100 : C.slate200}`,
            }}>
              <div className="text-muted-foreground" style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
                New Codes (Not in Billing)
              </div>
              <div style={{ fontSize: 22, fontWeight: 800, color: aiAnalysis.aiOnlyCount > 0 ? C.emerald600 : C.slate400, fontFamily: "monospace" }}>
                {aiAnalysis.aiOnlyCount}
              </div>
              <div className="text-muted-foreground" style={{ fontSize: 11, marginTop: 2 }}>
                {aiAnalysis.aiOnlyCount > 0 ? "Potential revenue opportunity" : "All codes already billed"}
              </div>
            </div>

            {/* Code source breakdown */}
            <div style={{
              background: "hsl(var(--card))", borderRadius: 8, padding: "12px 16px",
              border: `1px solid ${C.slate200}`,
            }}>
              <div className="text-muted-foreground" style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
                Data Sources
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 4 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11 }}>
                  <span style={{ width: 8, height: 8, borderRadius: 999, background: C.slate500, flexShrink: 0 }} />
                  <span className="text-muted-foreground font-medium">Billing (OpenEMR)</span>
                  <span className="text-foreground font-mono font-bold" style={{ marginLeft: "auto" }}>
                    {hccCount}
                  </span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11 }}>
                  <span style={{ width: 8, height: 8, borderRadius: 999, background: C.emerald500, flexShrink: 0 }} />
                  <span className="text-muted-foreground font-medium">AI Analysis</span>
                  <span className="text-emerald-600 dark:text-emerald-400 font-mono font-bold" style={{ marginLeft: "auto" }}>
                    +{aiAnalysis.aiOnlyCount}
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* List new AI-only codes */}
          {aiAnalysis.aiOnlyCount > 0 && (
            <div style={{ marginTop: 12 }}>
              <div className="text-muted-foreground" style={{ fontSize: 11, fontWeight: 600, marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                AI-Identified Codes Not Yet in Billing
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {aiAnalysis.aiOnlyCodes.map((dx: AIDiagnosis, i: number) => (
                  <span key={dx.code || dx.icd10_code || i} className="bg-card text-foreground border border-emerald-100 dark:border-emerald-800" style={{
                    display: "inline-flex", alignItems: "center", gap: 6,
                    padding: "4px 10px", borderRadius: 6, fontSize: 11, fontWeight: 500,
                  }}>
                    <span className="font-mono font-bold text-emerald-600 dark:text-emerald-400">
                      {dx.icd10_code || dx.code}
                    </span>
                    {dx.description || dx.condition || dx.diagnosis || ""}
                    {(dx.hcc_code || dx.hcc || dx.hcc_mapping?.hcc_code) && (
                      <span className="text-primary bg-primary/10 border border-primary/20" style={{
                        padding: "1px 6px", borderRadius: 4, fontSize: 9, fontWeight: 700,
                      }}>
                        {dx.hcc_code || dx.hcc || dx.hcc_mapping?.hcc_code}
                      </span>
                    )}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Clinical Highlights — AI-extracted from most recent encounter */}
      <ClinicalHighlightsPanel pid={pid} />

      {/* Main Grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 0.66fr",
          gap: 24,
        }}
      >
      {/* ============ LEFT COLUMN (60%) ============ */}
      <div className="animate-slide-up stagger-2" style={{ display: "flex", flexDirection: "column", gap: 24 }}>
        {/* Active Problems */}
        <Card noPadding className="hover-lift">
          <SectionHeader
            title="Active Problems"
            icon={
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
                <rect x="8" y="2" width="8" height="4" rx="1" ry="1" />
              </svg>
            }
            count={
              problemItems.length || undefined
            }
          />
          <div style={{ padding: "0 0 0 0" }}>
            <PanelWithTimeout
              loading={problemsLoading}
              onRetry={onRetryProblems}
              skeleton={<SkeletonRows count={5} />}
            >
            {!problemItems.length ? (
              <div style={{ padding: "32px 20px", textAlign: "center" }}>
                <svg
                  width="24"
                  height="24"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke={C.slate400}
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  style={{ marginBottom: 8 }}
                >
                  <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
                  <rect x="8" y="2" width="8" height="4" rx="1" ry="1" />
                </svg>
                <div className="text-sm font-semibold text-foreground" style={{ marginBottom: 4 }}>
                  No active problems
                </div>
                {hasEncountersWithNotes ? (
                  <>
                    <div className="text-sm text-muted-foreground" style={{ marginBottom: 12 }}>
                      Run analysis on encounters to identify conditions
                    </div>
                    <button
                      onClick={() => setActiveTab("encounters")}
                      className="bg-primary/10 text-primary border border-primary"
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 6,
                        padding: "8px 16px",
                        borderRadius: 8,
                        fontSize: 13,
                        fontWeight: 600,
                        cursor: "pointer",
                      }}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
                      </svg>
                      Go to Encounters
                    </button>
                  </>
                ) : (
                  <div className="text-sm text-muted-foreground">
                    No encounters with clinical notes found
                  </div>
                )}
              </div>
            ) : (
              <div>
                {/* Table header */}
                <div
                  className="bg-muted border-y border-border"
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr 140px 120px",
                    padding: "8px 20px",
                  }}
                >
                  <span className="text-muted-foreground" style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>Condition</span>
                  <span className="text-muted-foreground" style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>ICD-10</span>
                  <span className="text-muted-foreground" style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>Onset</span>
                </div>
                {/* Rows */}
                {problemItems
                  .slice(0, 15)
                  .map((p: ProblemItem, i: number) => {
                    const icdCode = p.icd10_code || p.diagnosis_code || "\u2014";
                    const condLabel = p.title || p.condition || p.diagnosis || "\u2014";
                    return (
                    <div
                      key={p.icd10_code || p.diagnosis_code || p.title || i}
                      style={{
                        display: "grid",
                        gridTemplateColumns: "1fr 140px 120px",
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
                        className="text-sm font-medium text-foreground"
                      >
                        {condLabel}
                      </span>
                      <span>
                        <WithTooltip
                          tip={`ICD-10: ${icdCode} \u2014 ${condLabel}. HCC-mapped codes contribute to the patient's V28 RAF risk score. Onset: ${formatDate(p.begdate || p.onset_date || p.date)}.`}
                        >
                          <span
                            data-testid={`hcc-chip-${icdCode}`}
                            className="text-xs font-semibold font-mono bg-muted text-foreground border border-border"
                            style={{
                              display: "inline-block",
                              padding: "2px 8px",
                              borderRadius: 4,
                              cursor: "help",
                            }}
                          >
                            {icdCode}
                          </span>
                        </WithTooltip>
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {formatDate(p.begdate || p.onset_date || p.date)}
                      </span>
                    </div>
                    );
                  })}
              </div>
            )}
            </PanelWithTimeout>
          </div>
        </Card>

        {/* Recent Encounters */}
        <Card noPadding className="hover-lift">
          <SectionHeader
            title="Recent Encounters"
            icon={
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
              </svg>
            }
            count={encounters?.encounters?.length || undefined}
          />
          <div>
            <PanelWithTimeout
              loading={encountersLoading}
              onRetry={onRetryEncounters}
              skeleton={<SkeletonRows count={5} twoCol={false} />}
            >
            {!encounters?.encounters?.length ? (
              <EmptyState
                title="No encounters found"
                icon={
                  <svg
                    width="24"
                    height="24"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  >
                    <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
                  </svg>
                }
              />
            ) : (
              <div>
                {encounters.encounters.slice(0, 5).map((enc: EncounterItem) => {
                  const hasNotes = !!enc.notes || !!enc.has_notes;
                  return (
                    <WithTooltip
                      key={enc.encounter_id}
                      tip={`Click to see full encounter details and billing codes. ${hasNotes ? "Clinical notes available — run Analyze to extract diagnoses." : "No clinical notes attached to this encounter."}`}
                      side="left"
                    >
                    <div
                      data-testid={`encounter-row-${enc.encounter_id}`}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        padding: "12px 20px",
                        borderTop: `1px solid ${C.slate100}`,
                        transition: "background 0.1s",
                        cursor: "pointer",
                      }}
                      onClick={() => setActiveTab("encounters")}
                      onMouseEnter={(e) =>
                        (e.currentTarget.style.background = C.slate100)
                      }
                      onMouseLeave={(e) =>
                        (e.currentTarget.style.background = "transparent")
                      }
                    >
                      <div>
                        <div
                          className="text-sm font-medium text-foreground"
                        >
                          {enc.reason || "Office Visit"}
                        </div>
                        <div
                          className="text-xs text-muted-foreground"
                          style={{ marginTop: 2 }}
                        >
                          {enc.provider_fname || enc.provider_lname
                            ? `${enc.provider_fname || ""} ${enc.provider_lname || ""}`.trim()
                            : "Provider not listed"}
                          {" \u00B7 "}
                          {formatDate(enc.date)}
                        </div>
                      </div>
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 8,
                        }}
                      >
                        {!hasNotes && (
                          <span
                            className="text-xs text-muted-foreground"
                          style={{
                              fontStyle: "italic",
                            }}
                          >
                            No notes
                          </span>
                        )}
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            analyzeMutation.mutate(enc.encounter_id);
                          }}
                          disabled={analyzeMutation.isPending || !hasNotes}
                          className="bg-card text-muted-foreground border border-border"
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 4,
                            padding: "5px 12px",
                            borderRadius: 6,
                            fontSize: 12,
                            fontWeight: 500,
                            cursor:
                              analyzeMutation.isPending || !hasNotes
                                ? "not-allowed"
                                : "pointer",
                            opacity:
                              analyzeMutation.isPending || !hasNotes
                                ? 0.5
                                : 1,
                          }}
                        >
                          {analyzeMutation.isPending &&
                          analyzeMutation.variables === enc.encounter_id ? (
                            <Spinner size={12} />
                          ) : null}
                          Analyze
                        </button>
                      </div>
                    </div>
                    </WithTooltip>
                  );
                })}
              </div>
            )}
            </PanelWithTimeout>
          </div>
        </Card>

        {/* Care Gaps (Recapture) */}
        <Card noPadding className="hover-lift">
          <SectionHeader
            title="Care Gaps"
            icon={
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke={C.amber600}
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01" />
              </svg>
            }
          />
          <div>
            <PanelWithTimeout
              loading={recaptureLoading}
              onRetry={onRetryRecapture}
              skeleton={<SkeletonRows count={4} />}
            >
            {!recaptureItems.length ? (
              <EmptyState
                state={(profile?.data_completeness?.completeness_pct ?? 100) < 60 ? "no-data" : "complete"}
                title={
                  (profile?.data_completeness?.completeness_pct ?? 100) < 60
                    ? "clinical notes missing — upload notes to find gaps"
                    : `all conditions documented for ${selectedYear}`
                }
                cta={
                  (profile?.data_completeness?.completeness_pct ?? 100) < 60
                    ? { label: "Upload Notes", href: "#documents" }
                    : undefined
                }
              />
            ) : (
              <div>
                {recaptureItems.map(
                  (gap: RecaptureGapItem, i: number) => {
                    const gapCode = gap.icd10_code || gap.hcc_code || gap.hcc || "\u2014";
                    const gapLabel = gap.condition || gap.hcc_label || gap.description || "\u2014";
                    const priority = gap.coefficient != null && Number(gap.coefficient) >= 0.3 ? "High" : "Medium";
                    return (
                    <WithTooltip
                      key={gap.hcc_code || gap.icd10_code || gap.hcc || `gap-${i}`}
                      tip={`${priority}-priority recapture gap. ${gapLabel} (${gapCode}) was documented in a prior year but has not been recaptured this measurement year. Recapturing this HCC restores the RAF coefficient to this year's risk score.`}
                      side="left"
                    >
                    <div
                      data-testid={`recapture-gap-row-${gapCode}`}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        padding: "12px 20px",
                        borderTop: `1px solid ${C.slate100}`,
                        borderLeft: `3px solid ${C.amber500}`,
                      }}
                    >
                      <div style={{ flex: 1 }}>
                        <div
                          className="text-sm font-medium text-foreground"
                        >
                          {gapLabel}
                        </div>
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 8,
                            marginTop: 4,
                          }}
                        >
                          <span
                            className="text-xs font-semibold font-mono bg-muted text-foreground border border-border"
                          style={{
                              display: "inline-block",
                              padding: "2px 8px",
                              borderRadius: 4,
                            }}
                          >
                            {gapCode}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {formatDate(gap.onset_date || gap.begdate)}
                          </span>
                        </div>
                      </div>
                    </div>
                    </WithTooltip>
                    );
                  }
                )}
              </div>
            )}
            </PanelWithTimeout>
          </div>
        </Card>
      </div>

      {/* ============ RIGHT COLUMN (40%) ============ */}
      <div className="animate-slide-up stagger-3" style={{ display: "flex", flexDirection: "column", gap: 24 }}>
        {/* Demographics */}
        <Card className="hover-lift">
          <SectionHeader
            title="Demographics"
            icon={
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                <circle cx="12" cy="7" r="4" />
              </svg>
            }
          />
          <PanelWithTimeout
            loading={profileLoading}
            onRetry={onRetryProfile}
            skeleton={<SkeletonDataRows count={7} />}
          >
            <div>
              <DataRow label="Date of Birth" value={formatDate(dob)} />
              <DataRow
                label="Sex"
                value={
                  sex
                    ? sex.charAt(0).toUpperCase() + sex.slice(1)
                    : "\u2014"
                }
              />
              <DataRow
                label="Race"
                value={
                  (profile?.demographics?.race as string) || patient?.race || "\u2014"
                }
              />
              <DataRow
                label="Ethnicity"
                value={
                  (profile?.demographics?.ethnicity as string) ||
                  patient?.ethnicity ||
                  "\u2014"
                }
              />
              <DataRow
                label="Language"
                value={
                  (profile?.demographics?.language as string) ||
                  patient?.language ||
                  "\u2014"
                }
              />
              <DataRow
                label="Address"
                value={
                  [
                    patient?.street,
                    patient?.city,
                    patient?.state,
                    patient?.postal_code,
                  ]
                    .filter(Boolean)
                    .join(", ") ||
                  (profile?.demographics?.address as string) ||
                  "\u2014"
                }
              />
              <DataRow
                label="Phone"
                value={
                  patient?.phone_home ||
                  patient?.phone_cell ||
                  (profile?.demographics?.phone as string) ||
                  "\u2014"
                }
              />
            </div>
          </PanelWithTimeout>
        </Card>

        {/* Insurance */}
        <Card className="hover-lift">
          <SectionHeader
            title="Insurance"
            icon={
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
              </svg>
            }
          />
          <PanelWithTimeout
            loading={profileLoading}
            onRetry={onRetryProfile}
            skeleton={<SkeletonDataRows count={4} />}
          >
            <div>
              <DataRow
                label="Plan Type"
                value={(profile?.enrollment as Record<string, string> | undefined)?.plan_type || "\u2014"}
              />
              <DataRow
                label="Dual Status"
                value={(profile?.enrollment as Record<string, string> | undefined)?.dual_status ?? "\u2014"}
              />
              <DataRow
                label="OREC"
                value={(profile?.enrollment as Record<string, string> | undefined)?.orec ?? "\u2014"}
              />
              <DataRow
                label="Enrolled Since"
                value={formatDate((profile?.enrollment as Record<string, string> | undefined)?.enrolled_since || (profile?.enrollment as Record<string, string> | undefined)?.start_date)}
              />
            </div>
          </PanelWithTimeout>
        </Card>

        {/* Data Completeness */}
        <Card className="hover-lift">
          <SectionHeader
            title="Data Completeness"
            icon={
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
              </svg>
            }
          />
          <PanelWithTimeout
            loading={profileLoading}
            onRetry={onRetryProfile}
            skeleton={<SkeletonChecklist count={10} />}
          >
            <DataCompletenessChecklist
              profile={profile}
              encounters={encounters}
              problems={problems}
              meds={meds}
              labSuspects={labSuspects}
              vitalsSuspects={vitalsSuspects}
              selectedYear={selectedYear}
            />
          </PanelWithTimeout>
        </Card>
      </div>
    </div>
    </div>
  );
}
