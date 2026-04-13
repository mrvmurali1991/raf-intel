"use client";

import React, { useState } from "react";
import type { Patient } from "@/types";
import type {
  PatientProfile,
  MedicationsResponse,
  ClinicalFindingsResponse,
  AllergiesResponse,
  ImmunizationsResponse,
  FamilyHistoryResponse,
  SdohResponse,
  MedicationGapsResponse,
} from "@/lib/api";
import {
  EmptyState,
  DataRow,
} from "@/components/healthcare-ui";
import {
  C,
  formatDate,
  SectionLoader,
  ClinicalSection,
  SimpleTable,
  FindingsList,
} from "./shared";
import type {
  ExtendedRafBreakdown,
  MedicationItem,
  ClinicalFindingItem,
  AllergyItem,
  ImmunizationItem,
  FamilyHistoryItem,
  SdohFactor,
  MedicationGapItem,
} from "./shared";

export function ClinicalTab({
  meds,
  medsLoading,
  vitalsSuspects,
  vitalsLoading,
  labSuspects,
  labsLoading,
  allergies,
  allergiesLoading,
  immunizations,
  immunizationsLoading,
  familyHistory,
  familyHistoryLoading,
  sdoh,
  sdohLoading,
  medGaps,
  medGapsLoading,
  patient,
  profile,
  profileLoading,
  breakdown,
  breakdownLoading,
}: {
  meds: MedicationsResponse | MedicationItem[] | undefined;
  medsLoading: boolean;
  vitalsSuspects: ClinicalFindingsResponse | ClinicalFindingItem[] | undefined;
  vitalsLoading: boolean;
  labSuspects: ClinicalFindingsResponse | ClinicalFindingItem[] | undefined;
  labsLoading: boolean;
  allergies: AllergiesResponse | AllergyItem[] | undefined;
  allergiesLoading: boolean;
  immunizations: ImmunizationsResponse | ImmunizationItem[] | undefined;
  immunizationsLoading: boolean;
  familyHistory: FamilyHistoryResponse | FamilyHistoryItem[] | undefined;
  familyHistoryLoading: boolean;
  sdoh: SdohResponse | SdohFactor[] | undefined;
  sdohLoading: boolean;
  medGaps: MedicationGapsResponse | MedicationGapItem[] | undefined;
  medGapsLoading: boolean;
  patient: Patient | undefined;
  profile: PatientProfile | undefined;
  profileLoading: boolean;
  breakdown: ExtendedRafBreakdown | undefined;
  breakdownLoading: boolean;
}) {
  const [activeSection, setActiveSection] = useState("demographics");

  const medItems: MedicationItem[] = Array.isArray(meds) ? meds : (meds as MedicationsResponse | undefined)?.medications ?? [];
  const vitalsItems: ClinicalFindingItem[] = Array.isArray(vitalsSuspects) ? vitalsSuspects : (vitalsSuspects as ClinicalFindingsResponse | undefined)?.suspects ?? [];
  const labItems: ClinicalFindingItem[] = Array.isArray(labSuspects) ? labSuspects : (labSuspects as ClinicalFindingsResponse | undefined)?.suspects ?? [];
  const allergyItems: AllergyItem[] = Array.isArray(allergies) ? allergies : (allergies as AllergiesResponse | undefined)?.allergies ?? [];
  const immunizationItems: ImmunizationItem[] = Array.isArray(immunizations) ? immunizations : (immunizations as ImmunizationsResponse | undefined)?.immunizations ?? [];
  const familyItems: FamilyHistoryItem[] = (() => {
    if (Array.isArray(familyHistory)) return familyHistory;
    const fhResp = familyHistory as any;
    if (fhResp?.history && Array.isArray(fhResp.history)) return fhResp.history;
    const fh = fhResp?.family_history;
    if (!fh || typeof fh !== "object") return [];
    const items: FamilyHistoryItem[] = [];
    if (fh.history_father) items.push({ condition: fh.history_father, relation: "Father", title: fh.history_father });
    if (fh.history_mother) items.push({ condition: fh.history_mother, relation: "Mother", title: fh.history_mother });
    if (fh.history_siblings) items.push({ condition: fh.history_siblings, relation: "Sibling", title: fh.history_siblings });
    if (fh.history_offspring) items.push({ condition: fh.history_offspring, relation: "Offspring", title: fh.history_offspring });
    if (fh.history_spouse) items.push({ condition: fh.history_spouse, relation: "Spouse", title: fh.history_spouse });
    const relMap: Record<string, string> = {
      relatives_cancer: "Cancer", relatives_diabetes: "Diabetes",
      relatives_heart_disease: "Heart Disease", relatives_hypertension: "Hypertension",
      relatives_stroke: "Stroke", relatives_epilepsy: "Epilepsy",
      relatives_mental_illness: "Mental Illness", relatives_suicide: "Suicide",
      relatives_arthritis: "Arthritis", relatives_asthma: "Asthma",
    };
    for (const [key, label] of Object.entries(relMap)) {
      const val = fh[key];
      if (val && val !== "" && val !== "N/A") {
        if (!items.length) items.push({ condition: `${label}: ${val}`, relation: "Family", title: label });
      }
    }
    return items;
  })();

  const sdohItems: SdohFactor[] = (() => {
    if (Array.isArray(sdoh)) return sdoh;
    const sr = sdoh as any;
    if (sr?.factors && Array.isArray(sr.factors)) return sr.factors;
    const items: SdohFactor[] = [];
    if (sr?.billed_z_codes?.length) {
      for (const z of sr.billed_z_codes) {
        items.push({ factor: z.code_text || z.code || "Z-code", category: z.code, description: z.code_text || "" });
      }
    }
    if (sr?.sdoh_form && typeof sr.sdoh_form === "object") {
      for (const [k, v] of Object.entries(sr.sdoh_form)) {
        if (v && v !== "" && v !== "N/A") items.push({ factor: k.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()), description: String(v) });
      }
    }
    if (!items.length && sr?.billable_highlights) {
      for (const [code, desc] of Object.entries(sr.billable_highlights)) {
        items.push({ factor: String(desc), category: code, description: `Billable Z-code: ${code}` });
      }
    }
    return items;
  })();

  const medGapItems: MedicationGapItem[] = (() => {
    if (Array.isArray(medGaps)) return medGaps;
    const mg = medGaps as any;
    if (mg?.gaps && Array.isArray(mg.gaps)) {
      return mg.gaps.map((g: any) => ({
        condition: g.description || g.condition || g.gap || "",
        medication: g.drug || g.medication || "",
        drug: g.drug || "",
        icd10_code: g.icd_code || g.icd10_code || "",
        evidence: g.evidence || g.rationale || `Medication ${g.drug || ""} suggests unrecorded diagnosis`,
        gap: g.description || g.gap || "",
      }));
    }
    return [];
  })();

  const sections = [
    { id: "demographics", label: "Demographics" },
    { id: "insurance", label: "Insurance" },
    { id: "medications", label: "Medications" },
    { id: "vitals", label: "Vitals" },
    { id: "labs", label: "Labs" },
    { id: "allergies", label: "Allergies" },
    { id: "immunizations", label: "Immunizations" },
    { id: "family", label: "Family History" },
    { id: "sdoh", label: "SDOH" },
    { id: "medgaps", label: "Medication Gaps" },
  ];

  return (
    <div style={{ display: "flex", gap: 24 }}>
      {/* Left nav */}
      <nav
        style={{
          width: 200,
          flexShrink: 0,
          position: "sticky",
          top: 180,
          alignSelf: "flex-start",
        }}
      >
        {sections.map((s) => (
          <button
            key={s.id}
            onClick={() => setActiveSection(s.id)}
            style={{
              display: "block",
              width: "100%",
              padding: "10px 14px",
              borderRadius: 8,
              border: "none",
              textAlign: "left",
              fontSize: 13,
              fontWeight: activeSection === s.id ? 600 : 500,
              color: activeSection === s.id ? C.white : C.slate600,
              background:
                activeSection === s.id ? C.slate800 : "transparent",
              cursor: "pointer",
              marginBottom: 2,
              transition: "all 0.15s",
            }}
            onMouseEnter={(e) => {
              if (activeSection !== s.id) {
                e.currentTarget.style.background = C.slate100;
              }
            }}
            onMouseLeave={(e) => {
              if (activeSection !== s.id) {
                e.currentTarget.style.background = "transparent";
              }
            }}
          >
            {s.label}
          </button>
        ))}
      </nav>

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {activeSection === "demographics" && (
          <ClinicalSection title="Patient Demographics" loading={profileLoading}>
            <div style={{ padding: "16px 20px" }}>
              {(() => {
                const dob = (patient?.DOB || patient?.dob || profile?.demographics?.dob) as string | undefined;
                const sex = (patient?.sex || profile?.demographics?.sex) as string | undefined;
                const rawRace = (profile?.demographics?.race as string) || patient?.race || "";
                const rawEth = (profile?.demographics?.ethnicity as string) || patient?.ethnicity || "";
                const language = (profile?.demographics?.language as string) || patient?.language || "\u2014";
                const address = [patient?.street, patient?.city, patient?.state, patient?.postal_code].filter(Boolean).join(", ") || (profile?.demographics?.address as string) || "\u2014";
                const phone = patient?.phone_home || patient?.phone_cell || (profile?.demographics?.phone as string) || "\u2014";
                const email = (patient as any)?.email || "\u2014";
                const enrollment = profile?.enrollment as Record<string, string> | undefined;
                const fmtLabel = (s: string) => s ? s.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()) : "\u2014";
                const race = fmtLabel(rawRace);
                const ethnicity = fmtLabel(rawEth);
                const fmtDual = (s?: string) => {
                  if (!s) return "\u2014";
                  if (s === "non_dual") return "Non-Dual";
                  if (s === "full_dual") return "Full Dual Eligible";
                  if (s === "partial_dual") return "Partial Dual";
                  return s.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
                };
                const fmtOrec = (o?: string) => {
                  if (o === "0") return "0 \u2014 Aged (\u226565)";
                  if (o === "1") return "1 \u2014 Disabled (<65)";
                  if (o === "2") return "2 \u2014 ESRD";
                  return o || "\u2014";
                };
                return (
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 32px" }}>
                    <div>
                      <DataRow label="Date of Birth" value={dob ? formatDate(dob) : "\u2014"} />
                      <DataRow label="Sex" value={sex ? sex.charAt(0).toUpperCase() + sex.slice(1) : "\u2014"} />
                      <DataRow label="Race" value={race} />
                      <DataRow label="Ethnicity" value={ethnicity} />
                      <DataRow label="Language" value={language} />
                      <DataRow label="Email" value={email} />
                    </div>
                    <div>
                      <DataRow label="Address" value={address} />
                      <DataRow label="Phone" value={phone} />
                      <DataRow label="Plan Type" value={enrollment?.plan_type || "\u2014"} />
                      <DataRow label="Enrolled Since" value={enrollment?.enrolled_since ? formatDate(enrollment.enrolled_since) : "\u2014"} />
                      <DataRow label="Dual Status" value={fmtDual(enrollment?.dual_status)} />
                      <DataRow label="OREC" value={fmtOrec(enrollment?.orec)} />
                    </div>
                  </div>
                );
              })()}
            </div>
          </ClinicalSection>
        )}

        {activeSection === "insurance" && (
          <ClinicalSection title="Insurance & Enrollment" loading={profileLoading}>
            <div style={{ padding: "16px 20px" }}>
              {(() => {
                const enrollment = profile?.enrollment as Record<string, string> | undefined;
                const fmtDual = (s?: string) => {
                  if (!s) return "\u2014";
                  if (s === "non_dual") return "Non-Dual";
                  if (s === "full_dual") return "Full Dual Eligible";
                  if (s === "partial_dual") return "Partial Dual";
                  return s.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
                };
                const fmtOrec = (o?: string) => {
                  if (o === "0") return "0 \u2014 Aged (\u226565)";
                  if (o === "1") return "1 \u2014 Disabled (<65)";
                  if (o === "2") return "2 \u2014 ESRD";
                  return o || "\u2014";
                };
                return (
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 32px" }}>
                    <div>
                      <DataRow label="Primary Insurance" value={enrollment?.primary_insurance || "\u2014"} />
                      <DataRow label="Secondary Insurance" value={enrollment?.secondary_insurance || "\u2014"} />
                      <DataRow label="Plan Type" value={enrollment?.plan_type || "\u2014"} />
                    </div>
                    <div>
                      <DataRow label="Enrolled Since" value={enrollment?.enrolled_since ? formatDate(enrollment.enrolled_since) : "\u2014"} />
                      <DataRow label="Dual Status" value={fmtDual(enrollment?.dual_status)} />
                      <DataRow label="OREC" value={fmtOrec(enrollment?.orec)} />
                    </div>
                  </div>
                );
              })()}
            </div>
          </ClinicalSection>
        )}

        {activeSection === "medications" && (
          <ClinicalSection title="Active Medications" loading={medsLoading}>
            {!medItems.length ? (
              <EmptyState title="No active medications" />
            ) : (
              <SimpleTable
                headers={["Drug", "Dose", "Frequency", "Date"]}
                rows={medItems.map((m: MedicationItem) => [
                  m.drug || m.title || m.medication || "\u2014",
                  m.dosage || m.dose || "\u2014",
                  m.frequency || m.route || "\u2014",
                  formatDate(m.begdate || m.start_date || m.date),
                ])}
              />
            )}
          </ClinicalSection>
        )}

        {activeSection === "vitals" && (
          <ClinicalSection title="Vitals" loading={vitalsLoading}>
            {(() => {
              const v = (vitalsSuspects as any)?.latest_vitals || (profile as any)?.vitals?.latest;
              if (!v) return <EmptyState title="No vitals recorded" />;
              const bmi = v.weight && v.height ? (v.weight / ((v.height / 100) ** 2)).toFixed(1) : null;
              return (
                <div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "0 32px", padding: "16px 20px" }}>
                    <div>
                      <DataRow label="Weight" value={v.weight ? `${v.weight} kg (${(v.weight * 2.205).toFixed(1)} lbs)` : "\u2014"} />
                      <DataRow label="Height" value={v.height ? `${v.height} cm (${(v.height / 2.54).toFixed(0)}\u2033)` : "\u2014"} />
                      <DataRow label="BMI" value={bmi ? `${bmi} kg/m\u00B2` : "\u2014"} />
                    </div>
                    <div>
                      <DataRow label="Blood Pressure" value={v.bps && v.bpd ? `${v.bps}/${v.bpd} mmHg` : "\u2014"} />
                      <DataRow label="Temperature" value={v.temperature ? `${v.temperature} \u00B0F` : "\u2014"} />
                      <DataRow label="Pulse" value={v.pulse ? `${v.pulse} bpm` : "\u2014"} />
                    </div>
                    <div>
                      <DataRow label="Respiration" value={v.respiration ? `${v.respiration} /min` : "\u2014"} />
                      <DataRow label="O\u2082 Saturation" value={v.oxygen_saturation ? `${v.oxygen_saturation}%` : "\u2014"} />
                      <DataRow label="Recorded" value={formatDate(v.date)} />
                    </div>
                  </div>
                  {vitalsItems.length > 0 && (
                    <div style={{ borderTop: `1px solid #e2e8f0`, padding: "12px 20px 0" }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: "#475569", marginBottom: 8 }}>Vitals-Derived Findings</div>
                      <FindingsList
                        items={vitalsItems.map((s: ClinicalFindingItem) => ({
                          name: s.condition || s.finding || "\u2014",
                          detail: s.evidence || s.rationale || s.detail || "",
                          icd10: s.icd10_code,
                        }))}
                      />
                    </div>
                  )}
                </div>
              );
            })()}
          </ClinicalSection>
        )}

        {activeSection === "labs" && (
          <ClinicalSection title="Lab Results" loading={labsLoading}>
            {(() => {
              const labResults = ((labSuspects as any)?.labs?.results || []) as Array<{ id?: number; result_text?: string; date?: string; encounter?: number }>;
              if (!labResults.length && !labItems.length) return <EmptyState title="No lab results" />;
              const parsed = labResults.map((l) => {
                const rt = l.result_text || "";
                const nameMatch = rt.match(/^([^:]+):/);
                const valMatch = rt.match(/:\s*([^\(]+)/);
                const refMatch = rt.match(/\(Ref:\s*([^)]+)\)/);
                const flagMatch = rt.match(/\[([A-Z]+)\]/);
                return {
                  name: nameMatch ? nameMatch[1].trim() : rt,
                  value: valMatch ? valMatch[1].trim() : "\u2014",
                  reference: refMatch ? refMatch[1].trim() : "\u2014",
                  flag: flagMatch ? flagMatch[1] : "NORMAL",
                  date: l.date,
                };
              });
              return (
                <div>
                  {parsed.length > 0 && (
                    <SimpleTable
                      headers={["Test", "Result", "Reference Range", "Flag", "Date"]}
                      rows={parsed.map((l) => [
                        l.name,
                        l.value,
                        l.reference,
                        l.flag === "ABNORMAL" || l.flag === "HIGH" || l.flag === "LOW"
                          ? `\u26A0 ${l.flag}`
                          : l.flag === "NORMAL" ? "\u2713 Normal" : l.flag,
                        formatDate(l.date),
                      ])}
                    />
                  )}
                  {labItems.length > 0 && (
                    <div style={{ borderTop: `1px solid #e2e8f0`, padding: "12px 20px 0" }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: "#475569", marginBottom: 8 }}>Lab-Derived Suspect Conditions</div>
                      <FindingsList
                        items={labItems.map((s: ClinicalFindingItem) => ({
                          name: s.condition || s.finding || "\u2014",
                          detail: s.evidence || s.rationale || "",
                          icd10: s.icd10_code,
                          hcc: s.hcc_code,
                        }))}
                      />
                    </div>
                  )}
                </div>
              );
            })()}
          </ClinicalSection>
        )}

        {activeSection === "allergies" && (
          <ClinicalSection title="Allergies" loading={allergiesLoading}>
            {!allergyItems.length ? (
              <EmptyState title="No allergies documented" />
            ) : (
              <FindingsList
                items={allergyItems.map(
                  (a: AllergyItem) => ({
                    name: a.title || a.allergen || a.substance || "\u2014",
                    detail: [a.reaction, a.severity].filter(Boolean).join(" \u00B7 "),
                  })
                )}
              />
            )}
          </ClinicalSection>
        )}

        {activeSection === "immunizations" && (
          <ClinicalSection title="Immunizations" loading={immunizationsLoading}>
            {!immunizationItems.length ? (
              <EmptyState title="No immunizations documented" />
            ) : (
              <SimpleTable
                headers={["Vaccine", "Date"]}
                rows={immunizationItems.map((imm: ImmunizationItem) => [
                  imm.title || imm.vaccine || imm.immunization || "\u2014",
                  formatDate(imm.administered_date || imm.date || imm.create_date),
                ])}
              />
            )}
          </ClinicalSection>
        )}

        {activeSection === "family" && (
          <ClinicalSection title="Family History" loading={familyHistoryLoading}>
            {!familyItems.length ? (
              <EmptyState title="No family history documented" />
            ) : (
              <FindingsList
                items={familyItems.map((fh: FamilyHistoryItem) => ({
                  name: fh.condition || fh.title || fh.diagnosis || "\u2014",
                  detail: fh.relation || "",
                }))}
              />
            )}
          </ClinicalSection>
        )}

        {activeSection === "sdoh" && (
          <ClinicalSection title="Social Determinants of Health" loading={sdohLoading}>
            {!sdohItems.length ? (
              <EmptyState title="No SDOH data available" />
            ) : (
              <FindingsList
                items={sdohItems.map(
                  (s: SdohFactor) => ({
                    name: s.factor || s.category || "\u2014",
                    detail: s.description || "",
                  })
                )}
              />
            )}
          </ClinicalSection>
        )}

        {activeSection === "medgaps" && (
          <ClinicalSection title="Medication-Derived Gaps" loading={medGapsLoading}>
            {!medGapItems.length ? (
              <EmptyState title="No medication gaps identified" />
            ) : (
              <FindingsList
                items={medGapItems.map((g: MedicationGapItem) => ({
                  name: g.condition || g.gap || "\u2014",
                  detail: `${g.medication || g.drug || ""} ${g.evidence || g.rationale || ""}`.trim(),
                  icd10: g.icd10_code,
                }))}
              />
            )}
          </ClinicalSection>
        )}
      </div>
    </div>
  );
}
