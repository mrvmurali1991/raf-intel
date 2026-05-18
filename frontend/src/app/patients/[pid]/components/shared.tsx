"use client";

import React, { useState, useEffect, useRef } from "react";
import type { MEATEvidence, DBSuspect, AnalysisResult } from "@/types";
import type {
  PatientProfile,
  RafBreakdown,
  RafHistoryResponse,
  PatientEncountersResponse,
  PatientSuspectsResponse,
  MedicationsResponse,
  ClinicalFindingsResponse,
  AllergiesResponse,
  ImmunizationsResponse,
  FamilyHistoryResponse,
  SdohResponse,
  MedicationGapsResponse,
  ProblemListResponse,
  RecaptureGapsResponse,
  AuditPackagesResponse,
  DocumentsResponse,
  DocumentAnalysisResult,
  CrosswalkResult,
} from "@/lib/api";
import {
  SectionHeader,
  EmptyState,
  ProgressBar,
} from "@/components/healthcare-ui";
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from "@/components/ui/tooltip";

// ---------------------------------------------------------------------------
// Local Types
// ---------------------------------------------------------------------------

/** HCC detail from the RAF breakdown endpoint (runtime shape is wider than RafBreakdown type) */
export interface HCCDetail {
  hcc_code?: string;
  code?: string;
  hcc_label?: string;
  label?: string;
  coefficient?: number;
  hcc_coefficient?: number;
  icd10_codes?: Array<string | { code?: string; icd10_code?: string }>;
  supporting_icd10s?: Array<string | { code?: string; icd10_code?: string }>;
  meat_status?: "complete" | "partial" | "missing";
  meat_evidence?: MEATEvidence;
  meat_status_detail?: { monitor?: boolean; evaluate?: boolean; assess?: boolean; treat?: boolean };
  meat_completeness?: Record<string, boolean>;
}

/** Extended RAF breakdown as returned at runtime (wider than the strict api type) */
export interface ExtendedRafBreakdown extends Omit<RafBreakdown, "hcc_details" | "raf_score" | "model_segment" | "measurement_year"> {
  total_raf?: number;
  raf_score?: number;
  hcc_details?: HCCDetail[];
  hcc_count?: number;
  model_segment?: string;
  measurement_year?: number;
  demographic_base?: number;
  /** Alias used by legacy API responses; prefer demographic_base */
  demographic_score?: number;
  disease_score?: number;
  interaction_score?: number;
  final_raf?: number;
}

/** Score history entry (from scores/history endpoint) */
export interface ScoreHistoryEntry {
  id?: number;
  raf_score?: number;
  score?: number;
  total_score?: number;
  year?: number;
  measurement_year?: number;
  model?: string;
  calculated_at?: string;
  created_at?: string;
}

/** Encounter item from the encounters endpoint */
export interface EncounterItem {
  encounter_id: number;
  date: string;
  encounter_date?: string;
  reason?: string;
  provider_fname?: string;
  provider_lname?: string;
  notes?: string;
  has_notes?: boolean;
  analyzed_at?: string;
  has_analysis?: boolean;
  analysis?: AnalysisResult;
  cached_analysis?: AnalysisResult;
}

/** Suspect item from the suspects endpoint (DB row) */
export interface SuspectItem extends DBSuspect {
  condition?: string;
  suspect_condition?: string;
  hcc_description?: string;
  icd10_code?: string;
  icd10?: string;
  hcc_code?: string;
  rationale?: string;
  evidence?: string;
  confidence?: number;
  hcc_coefficient?: number;
  suspect_id?: number;
  meat_evidence?: MEATEvidence;
  source?: string;
  identified_at?: string;
}

/** Problem list item */
export interface ProblemItem {
  title?: string;
  condition?: string;
  diagnosis?: string;
  icd10_code?: string;
  diagnosis_code?: string;
  begdate?: string;
  onset_date?: string;
  date?: string;
}

/** Recapture gap item */
export interface RecaptureGapItem {
  hcc_code?: string;
  hcc?: string;
  description?: string;
  label?: string;
  hcc_label?: string;
  condition?: string;
  last_coded_year?: number;
  last_captured_year?: number;
  prior_year?: number;
  evidence?: string;
  icd10_code?: string;
  onset_date?: string;
  begdate?: string;
  status?: string;
  coefficient?: number;
}

/** Medication item */
export interface MedicationItem {
  drug?: string;
  title?: string;
  medication?: string;
  dosage?: string;
  dose?: string;
  frequency?: string;
  route?: string;
  begdate?: string;
  start_date?: string;
  date?: string;
}

/** Clinical finding item (vitals/labs) */
export interface ClinicalFindingItem {
  condition?: string;
  finding?: string;
  evidence?: string;
  rationale?: string;
  detail?: string;
  icd10_code?: string;
  hcc_code?: string;
}

/** Allergy item */
export interface AllergyItem {
  title?: string;
  allergen?: string;
  substance?: string;
  /** Drug/substance category (e.g. "sulfa", "penicillin") */
  category?: string;
  reaction?: string;
  severity?: string;
  begdate?: string;
}

/** Immunization item */
export interface ImmunizationItem {
  title?: string;
  vaccine?: string;
  immunization?: string;
  administered_date?: string;
  create_date?: string;
  date?: string;
}

/** Family history item */
export interface FamilyHistoryItem {
  condition?: string;
  title?: string;
  diagnosis?: string;
  relation?: string;
  relative?: string;
  age_at_onset?: number;
}

/** SDOH factor */
export interface SdohFactor {
  category?: string;
  factor?: string;
  description?: string;
  risk_level?: string;
  screening_date?: string;
}

/** Medication gap */
export interface MedicationGapItem {
  medication?: string;
  condition?: string;
  gap?: string;
  gap_type?: string;
  drug?: string;
  evidence?: string;
  rationale?: string;
  recommendation?: string;
  severity?: string;
  icd10_code?: string;
}

/** Document analysis data with diagnoses merged in */
export interface DocumentAnalysisData extends DocumentAnalysisResult {
  diagnoses?: Array<{
    id?: number;
    icd10_code?: string;
    icd_code?: string;
    description?: string;
    diagnosis?: string;
    hcc_code?: string;
    raf_weight?: number;
    confidence?: number;
    status?: string;
    meat_status?: string;
    meat_evidence?: MEATEvidence;
    meat?: { M?: string; E?: string; A?: string; T?: string };
  }>;
}

/** Draft RAF data from document */
export interface DraftRAFData {
  current_raf_score?: number;
  draft_raf_score?: number;
  draft_score?: number;
  raf_delta?: number;
  draft_raf?: number;
  new_hccs?: Array<string | { code?: string; hcc_code?: string; label?: string; description?: string; coefficient?: number; raf_weight?: number }>;
  new_hcc_codes?: Array<string | { code?: string; hcc_code?: string; label?: string; description?: string; coefficient?: number; raf_weight?: number }>;
  existing_hcc_codes?: string[];
  estimated_revenue_impact?: number;
  revenue_impact?: number;
}

/** Audit package item */
export interface AuditPackageItem {
  id: number;
  pid?: number;
  year?: number;
  filepath?: string;
  file_size_bytes?: number;
  created_at: string;
}

/** Axios-like error shape for mutation error handlers */
export interface ApiError {
  response?: { data?: { detail?: string } };
  message?: string;
}

// ---------------------------------------------------------------------------
// Design Tokens
// ---------------------------------------------------------------------------
export const C = {
  bg: "#F8FAFC",
  white: "#FFFFFF",
  slate900: "#0F172A",
  slate800: "#1E293B",
  slate700: "#334155",
  slate600: "#475569",
  slate500: "#64748B",
  // slate400 promoted from #94A3B8 (2.84:1 on white — FAILS WCAG AA for text)
  // to #64748B (4.59:1 — PASSES AA). 111 of 114 references in the patient
  // detail tree use this token for label/caption TEXT; the prior hex
  // failed accessibility audit (UX-review #3 / round-2 #G2). Decorative
  // borders and SVG strokes that previously used slate-400 are simply
  // marginally darker now — still well within the design language.
  slate400: "#64748B",
  slate300: "#CBD5E1",
  slate200: "#E2E8F0",
  slate100: "#F1F5F9",
  blue600: "#0f766e",
  blue500: "#0d9488",
  blue100: "#ccfbf1",
  blue50: "#f0fdfa",
  emerald600: "#059669",
  emerald500: "#10B981",
  emerald100: "#D1FAE5",
  emerald50: "#ECFDF5",
  amber600: "#D97706",
  amber500: "#F59E0B",
  amber100: "#FEF3C7",
  amber50: "#FFFBEB",
  red600: "#DC2626",
  red500: "#EF4444",
  red100: "#FEE2E2",
  red50: "#FEF2F2",
  purple600: "#9333EA",
  purple100: "#EDE9FE",
  purple50: "#F5F3FF",
  amber700: "#B45309",
  orange500: "#F97316",
  gray200: "#E5E7EB",
  gray400: "#9CA3AF",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
export function formatDate(d: string | null | undefined): string {
  if (!d) return "\u2014";
  try {
    return new Date(d).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return d;
  }
}

export function rafScoreColor(score: number): string {
  if (score >= 3.0) return C.red600;
  if (score >= 1.5) return C.amber600;
  return C.emerald600;
}

export function Spinner({ size = 16 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      style={{ animation: "spin 1s linear infinite" }}
    >
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <circle
        cx="12"
        cy="12"
        r="10"
        stroke={C.slate300}
        strokeWidth="3"
        fill="none"
      />
      <path
        d="M12 2a10 10 0 0 1 10 10"
        stroke={C.blue600}
        strokeWidth="3"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  );
}

export function SectionLoader({ label }: { label?: string }) {
  return (
    <div
      className="text-muted-foreground"
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 8,
        padding: "48px 0",
      }}
    >
      <Spinner size={18} />
      <span className="text-sm">{label || "Loading\u2026"}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skeleton primitives — shimmer class from globals.css
// ---------------------------------------------------------------------------

/** A single rectangular shimmer block */
export function SkeletonBlock({
  width = "100%",
  height = 14,
  radius = 6,
  style,
}: {
  width?: number | string;
  height?: number | string;
  radius?: number;
  style?: React.CSSProperties;
}) {
  return (
    <div
      className="shimmer"
      aria-hidden="true"
      style={{
        width,
        height,
        borderRadius: radius,
        background: C.slate200,
        ...style,
      }}
    />
  );
}

/** Skeleton for a table-like list rows (problems, encounters, care gaps) */
export function SkeletonRows({
  count = 5,
  twoCol = true,
}: {
  count?: number;
  twoCol?: boolean;
}) {
  return (
    <div aria-label="Loading content" aria-busy="true">
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          style={{
            display: "grid",
            gridTemplateColumns: twoCol ? "1fr 80px" : "1fr",
            gap: 12,
            padding: "10px 20px",
            borderBottom: `1px solid ${C.slate100}`,
            alignItems: "center",
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <SkeletonBlock height={13} width={`${70 - i * 5}%`} />
            <SkeletonBlock height={11} width="40%" />
          </div>
          {twoCol && <SkeletonBlock height={22} width={64} radius={4} />}
        </div>
      ))}
    </div>
  );
}

/** Skeleton for a demographics/insurance card — label + value rows */
export function SkeletonDataRows({ count = 5 }: { count?: number }) {
  return (
    <div aria-label="Loading content" aria-busy="true" style={{ padding: "8px 0" }}>
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "8px 20px",
            borderBottom: `1px solid ${C.slate100}`,
            gap: 16,
          }}
        >
          <SkeletonBlock height={12} width={80} />
          <SkeletonBlock height={12} width={`${40 + (i % 3) * 10}%`} />
        </div>
      ))}
    </div>
  );
}

/** Skeleton for a checklist (Data Completeness) — progress bar + rows */
export function SkeletonChecklist({ count = 8 }: { count?: number }) {
  return (
    <div aria-label="Loading content" aria-busy="true" style={{ display: "flex", flexDirection: "column", gap: 10, padding: "8px 0" }}>
      <SkeletonBlock height={6} width="100%" radius={4} style={{ marginBottom: 8 }} />
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <SkeletonBlock height={12} width={`${50 + (i % 4) * 8}px`} />
          <SkeletonBlock height={18} width={72} radius={4} />
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// PanelWithTimeout — wraps any loading panel with a 12 s hard timeout
// ---------------------------------------------------------------------------

interface PanelWithTimeoutProps {
  loading: boolean;
  skeleton: React.ReactNode;
  children: React.ReactNode;
  onRetry?: () => void;
  /** Override default 12 s timeout (ms) */
  timeoutMs?: number;
}

export function PanelWithTimeout({
  loading,
  skeleton,
  children,
  onRetry,
  timeoutMs = 12_000,
}: PanelWithTimeoutProps) {
  const [timedOut, setTimedOut] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!loading) {
      setTimedOut(false);
      if (timerRef.current) clearTimeout(timerRef.current);
      return;
    }
    timerRef.current = setTimeout(() => setTimedOut(true), timeoutMs);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [loading, timeoutMs]);

  if (!loading) return <>{children}</>;

  if (timedOut) {
    return (
      <div
        role="alert"
        className="text-muted-foreground"
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 8,
          padding: "32px 20px",
          textAlign: "center",
        }}
      >
        <svg
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke={C.slate400}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
        <span className="text-sm text-muted-foreground">
          Couldn&apos;t load this section
        </span>
        {onRetry && (
          <button
            onClick={() => {
              setTimedOut(false);
              onRetry();
            }}
            className="bg-card text-muted-foreground border-border"
            style={{
              marginTop: 4,
              padding: "6px 16px",
              borderRadius: 6,
              border: "1px solid",
              fontSize: 12,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Retry
          </button>
        )}
      </div>
    );
  }

  return <>{skeleton}</>;
}


// ---------------------------------------------------------------------------
// Card wrapper (inline styles)
// ---------------------------------------------------------------------------
export function Card({
  children,
  style,
  noPadding,
  className: extraClassName,
}: {
  children: React.ReactNode;
  style?: React.CSSProperties;
  noPadding?: boolean;
  className?: string;
}) {
  return (
    <div
      className={`premium-card bg-card border-border ${extraClassName || ""}`}
      style={{
        border: "1px solid",
        borderRadius: 10,
        padding: noPadding ? 0 : 20,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// MEAT Dots (local for encounters/raf detail)
// ---------------------------------------------------------------------------
type MeatEvidence = MEATEvidence | Record<string, string | boolean | null | undefined>;
export function MeatDots({ evidence }: { evidence?: MeatEvidence | null }) {
  const letters = [
    { key: "monitor" as const, alt: ["M", "m"], label: "M", full: "Monitor",  color: C.blue600,
      tip: "Monitored — patient's condition is being tracked (vitals, labs, symptoms)" },
    { key: "evaluate" as const, alt: ["E", "e"], label: "E", full: "Evaluate", color: C.purple600,
      tip: "Evaluated — clinician assessed status, ordered tests, or reviewed results" },
    { key: "assess" as const,   alt: ["A", "a"], label: "A", full: "Assessed", color: C.amber600,
      tip: "Assessed — diagnosis addressed in the clinical note or exam findings" },
    { key: "treat" as const,    alt: ["T", "t"], label: "T", full: "Treat",    color: C.emerald600,
      tip: "Treated — active intervention: prescription, procedure, or care plan" },
  ];
  const e = evidence as Record<string, string | boolean | null | undefined> | undefined | null;
  const rawExcerpt: string | undefined =
    e ? (e.raw_note_excerpt as string | undefined) || (e.rawNoteExcerpt as string | undefined) || (e.excerpt as string | undefined) : undefined;
  return (
    <TooltipProvider delay={200}>
      <div style={{ display: "inline-flex", gap: 4 }}>
        {letters.map(({ key, alt, label, full, color, tip }) => {
          const rawVal = e && (e[key] || alt.map((a) => e[a]).find(Boolean));
          const filled = !!rawVal;
          const phrase = typeof rawVal === "string" ? rawVal : undefined;
          const dotStyle: React.CSSProperties = {
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: 26,
            height: 26,
            borderRadius: 6,
            fontSize: 11,
            fontWeight: 800,
            backgroundColor: filled ? `${color}20` : "transparent",
            color: filled ? color : C.gray400,
            border: `2px solid ${filled ? color : C.gray200}`,
            transition: "all 0.2s",
            boxShadow: filled ? `0 2px 6px ${color}25` : "none",
            cursor: "help",
            fontFamily: "inherit",
            background: filled ? `${color}20` : "transparent",
          };
          const tipContent = (
            <span>
              <strong>{full}</strong>{" — "}
              {filled ? (phrase || "present") : "not documented"}
              {". "}
              {tip}
              {rawExcerpt && (
                <><br /><em className="opacity-70">Note excerpt: &ldquo;{rawExcerpt}&rdquo;</em></>
              )}
            </span>
          );
          return (
            <Tooltip key={key}>
              <TooltipTrigger
                render={
                  <button
                    type="button"
                    style={dotStyle}
                    aria-label={`${full}: ${filled ? (phrase || "present") : "not documented"} — CMS MEAT evidence standard`}
                  >
                    {label}
                  </button>
                }
              />
              <TooltipContent side="top" className="max-w-xs text-xs leading-relaxed">
                {tipContent}
              </TooltipContent>
            </Tooltip>
          );
        })}
      </div>
    </TooltipProvider>
  );
}

// ---------------------------------------------------------------------------
// ClinicalSection wrapper
// ---------------------------------------------------------------------------
export function ClinicalSection({
  title,
  loading,
  children,
}: {
  title: string;
  loading: boolean;
  children: React.ReactNode;
}) {
  return (
    <Card noPadding className="animate-fade-in">
      <SectionHeader title={title} />
      {loading ? <SectionLoader /> : children}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// SimpleTable
// ---------------------------------------------------------------------------
export function SimpleTable({
  headers,
  rows,
}: {
  headers: string[];
  rows: string[][];
}) {
  return (
    <div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: headers
            .map((_, i) => (i === 0 ? "1fr" : "auto"))
            .join(" "),
          padding: "10px 20px",
          background: `linear-gradient(135deg, ${C.slate100}, ${C.slate200}40)`,
          borderTop: `1px solid ${C.slate200}`,
          borderBottom: `2px solid ${C.slate200}`,
          gap: 16,
        }}
      >
        {headers.map((h) => (
          <span
            key={h}
            className="text-muted-foreground"
            style={{
              fontSize: 11,
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.06em",
            }}
          >
            {h}
          </span>
        ))}
      </div>
      {rows.map((row, i) => (
        <div
          key={`${row[0]}-${i}`}
          style={{
            display: "grid",
            gridTemplateColumns: headers
              .map((_, idx) => (idx === 0 ? "1fr" : "auto"))
              .join(" "),
            padding: "10px 20px",
            borderBottom: `1px solid ${C.slate100}`,
            background: i % 2 === 1 ? C.slate100 + "60" : "transparent",
            gap: 16,
            transition: "background 0.15s",
          }}
          onMouseEnter={(e) =>
            (e.currentTarget.style.background = C.slate100)
          }
          onMouseLeave={(e) =>
            (e.currentTarget.style.background = i % 2 === 1 ? C.slate100 + "60" : "transparent")
          }
        >
          {row.map((cell, j) => (
            <span
              key={j}
              style={{
                fontSize: 13,
                fontWeight: j === 0 ? 500 : 400,
                color: j === 0 ? C.slate800 : C.slate500,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {cell}
            </span>
          ))}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// FindingsList
// ---------------------------------------------------------------------------
export function FindingsList({
  items,
}: {
  items: {
    name: string;
    detail?: string;
    icd10?: string;
    hcc?: string;
  }[];
}) {
  return (
    <div>
      {items.map((item, i) => (
        <div
          key={item.icd10 || item.hcc || `${item.name}-${i}`}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "12px 20px",
            borderTop: i === 0 ? `1px solid ${C.slate200}` : "none",
            borderBottom: `1px solid ${C.slate100}`,
          }}
        >
          <div>
            <div
              className="text-foreground"
            style={{
                fontSize: 13,
                fontWeight: 500,
              }}
            >
              {item.name}
            </div>
            {item.detail && (
              <div
                className="text-muted-foreground"
              style={{
                  fontSize: 12,
                  marginTop: 2,
                }}
              >
                {item.detail}
              </div>
            )}
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            {item.icd10 && (
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
                {item.icd10}
              </span>
            )}
            {item.hcc && (
              <span
                style={{
                  display: "inline-block",
                  padding: "2px 8px",
                  borderRadius: 4,
                  fontSize: 11,
                  fontWeight: 600,
                  fontFamily: "monospace",
                  background: C.blue50,
                  color: C.blue600,
                  border: `1px solid ${C.blue100}`,
                }}
              >
                {item.hcc}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Model Segment label helpers (CMS-HCC V28 segment codes)
// ---------------------------------------------------------------------------

/**
 * Map CMS-HCC V28 segment codes (as used in hccinfhir coefficient key prefixes)
 * to human-readable long-form labels. Case-insensitive.
 *
 * Continuing Enrollee:
 *   cna/cnd/cfa/cfd/cpa/cpd - Community {Non|Full|Partial}-Dual {Aged|Disabled}
 *   ins                     - Institutional
 * New Enrollee (ne_*):
 *   ne_cna, ne_cnd, ne_cfa, ne_cfd, ne_cpa, ne_cpd, ne_ins
 */
const SEGMENT_LABELS: Record<string, string> = {
  cna: "Community, Non-Dual Aged",
  cnd: "Community, Non-Dual Disabled",
  cfa: "Community, Full-Dual Aged",
  cfd: "Community, Full-Dual Disabled",
  cpa: "Community, Partial-Dual Aged",
  cpd: "Community, Partial-Dual Disabled",
  ins: "Institutional",
};

export function segmentLabel(code?: string | null): string {
  if (!code) return "Community, Non-Dual Aged";
  const key = String(code).trim().toLowerCase();
  if (key.startsWith("ne_")) {
    const base = key.slice(3);
    const baseLabel = SEGMENT_LABELS[base];
    return baseLabel ? `New Enrollee - ${baseLabel}` : `New Enrollee (${code})`;
  }
  return SEGMENT_LABELS[key] ?? code;
}

export function segmentCodeUpper(code?: string | null): string {
  return (code ?? "CNA").toString().toUpperCase();
}

// ---------------------------------------------------------------------------
// WithTooltip — 200 ms delay, keyboard accessible, WCAG 2.1 AA
// ---------------------------------------------------------------------------

/**
 * Wraps any inline element with a shadcn Tooltip (200 ms open delay).
 *
 * Usage:
 *   <WithTooltip tip="Explain this chip">
 *     <span>Some chip</span>
 *   </WithTooltip>
 *
 * The child is rendered via `render` prop on TooltipTrigger so it keeps its
 * original DOM semantics (button, span, div, etc.). A `tabIndex` and
 * `aria-describedby` are added automatically by base-ui.
 */
export function WithTooltip({
  tip,
  side = "top",
  children,
}: {
  tip: React.ReactNode;
  side?: "top" | "bottom" | "left" | "right";
  children: React.ReactElement;
}) {
  return (
    <TooltipProvider delay={200}>
      <Tooltip>
        <TooltipTrigger render={children} />
        <TooltipContent side={side} className="max-w-xs text-xs leading-relaxed">
          {tip}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
