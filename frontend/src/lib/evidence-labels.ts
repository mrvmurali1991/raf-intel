/**
 * evidence-labels.ts
 * Single source of truth for converting raw backend evidence_type /
 * evidence source strings into human-readable display labels.
 *
 * Usage:
 *   import { humanizeEvidence } from "@/lib/evidence-labels";
 *   humanizeEvidence("evidence_v1")  // → "Lab evidence"
 *   humanizeEvidence("lab_result")   // → "Lab result"
 *   humanizeEvidence("claim_history")// → "Claims history"
 */

export const EVIDENCE_LABELS: Record<string, string> = {
  // Versioned pipeline evidence buckets
  evidence_v1: "Lab evidence",
  evidence_v2: "Clinical note evidence",
  evidence_v3: "Claims evidence",

  // Lab & diagnostics
  lab: "Lab result",
  lab_result: "Lab result",
  lab_signal: "Lab signal",
  lab_finding: "Lab finding",
  loinc: "Lab (LOINC)",

  // Claims / billing
  claims: "Claims data",
  claim: "Claims data",
  claim_history: "Claims history",

  // Clinical notes / NLP
  clinical_note: "Clinical documentation",
  note: "Clinical note",
  nlp: "Clinical note",
  nlp_note: "Clinical note",

  // Medications / drugs
  medication: "Medication history",
  drug: "Medication",
  drug_class: "Drug class",
  "drug-class": "Drug class",
  atc: "Drug (ATC)",

  // Encounter / visit
  encounter: "Encounter record",
  encounter_record: "Encounter record",
  referral: "Referral",

  // Problem list & history
  problem_list: "Problem list entry",
  historical: "Prior-year record",
  history: "Prior-year record",
  hist: "Prior-year record",
  recapture: "Recapture candidate",

  // Vitals / biometrics
  vitals: "Vital signs",

  // Imaging
  imaging: "Imaging study",
  radiology: "Radiology report",

  // Knowledge-graph rules
  kg_rule: "KG rule",
  "kg-rule": "KG rule",
  kg: "KG rule",
  rule: "Clinical rule",
  comorbidity: "Comorbidity pattern",

  // ICD / diagnosis
  icd10: "Diagnosis code",
  icd: "Diagnosis code",
  dx: "Diagnosis code",
  diagnosis: "Diagnosis code",

  // LLM / AI inference
  llm: "AI inference",

  // Other
  other: "Other evidence",
};

/**
 * Returns a human-readable label for a raw evidence_type string coming
 * from the backend. Falls back to Title-casing the raw value when the
 * string is not in the lookup table.
 *
 * Always safe to call with undefined / null — returns "Unknown" in that
 * case.
 */
export function humanizeEvidence(raw: string | null | undefined): string {
  if (!raw) return "Unknown";
  const key = raw.trim().toLowerCase();
  if (EVIDENCE_LABELS[key]) return EVIDENCE_LABELS[key];
  // Also try the original casing key for exact matches
  if (EVIDENCE_LABELS[raw.trim()]) return EVIDENCE_LABELS[raw.trim()];
  // Graceful fallback: replace underscores / hyphens and title-case each word
  return raw
    .replace(/[-_]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
