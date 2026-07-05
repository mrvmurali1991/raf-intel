"use client";

/**
 * ExplainPanel
 * ------------
 * "Why was this flagged?" drill-down for a single suspect condition.
 *
 *   GET /api/raf-central/{patientId}/suspect/{suspectId}/explain
 *
 * Right-anchored drawer (max 420px). Optional Accept / Dismiss footer lets
 * the reviewer act on the suspect without closing the drawer first.
 */

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { FocusTrap } from "@/components/ui/focus-trap";
import {
  AlertCircle,
  Calendar,
  Check,
  DollarSign,
  FileText,
  FlaskConical,
  Hash,
  History,
  Info,
  Link2,
  Loader2,
  Pill,
  Sparkles,
  TrendingUp,
  X,
  XCircle,
} from "lucide-react";

import api from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { CONFIDENCE_METHODOLOGY, confidenceTier } from "@/lib/confidence";
import { humanizeEvidence } from "@/lib/evidence-labels";
import type { SuspectMeat } from "@/components/raf-central/_shared";

export interface ExplainPanelProps {
  patientId: number;
  suspectId: number;
  suspectLabel: string;
  open: boolean;
  onClose: () => void;
  onAccept?: () => void | Promise<void>;
  onRequestDismiss?: () => void;
  busy?: "accept" | "dismiss" | null;
  /** Per-suspect MEAT letter booleans — rendered as [M][E][A][T] indicators. */
  suspectMeat?: SuspectMeat | null;
  /** Expected revenue uplift from accepting this suspect ($). */
  suspectDollarImpact?: number | null;
}

interface ContributingSignal {
  source: "medication" | "lab" | "history" | "nlp" | "note" | "other";
  label: string;
  value?: string | null;
  timestamp?: string | null;
}

// Expected backend fields (not yet sent — added in a future batch).
// Backend shape: clinical_rule_adjustments?: ClinicalRuleAdjustment[]
//                context_classification?: ContextClassification
//                evidence_date?: string   (ISO-8601 date of the source note)
interface ClinicalRuleAdjustment {
  rule_id: string;
  rule_name: string;
  explanation: string;
  confidence_delta: number; // e.g. -0.40
  failed: boolean;
}

type ContextClassification =
  | "positive"
  | "negated"
  | "hypothetical"
  | "historical"
  | "family"
  | "resolved";

interface ExplainResponse {
  suspect_id: number;
  patient_id: number;
  suspect_icd10: string;
  suspect_hcc: string;
  confidence: number;
  evidence_type: string;
  contributing_signals: ContributingSignal[];
  summary: string;
  // Optional — backend will populate in a future release
  clinical_rule_adjustments?: ClinicalRuleAdjustment[];
  context_classification?: ContextClassification;
  evidence_date?: string; // ISO-8601; used for stale-evidence banner
  // Rich evidence detail blob — verbatim from raf_suspect_conditions.
  // Contains type-specific fields (medication_signal_id, lab thresholds,
  // comorbidity patterns, NLP sentences, etc.)
  evidence_detail_raw?: Record<string, unknown> | unknown[] | null;
}

type SourceKey = ContributingSignal["source"];

const SOURCE_META: Record<
  SourceKey,
  { icon: typeof Pill; label: string; accent: string }
> = {
  medication: {
    icon: Pill,
    label: "Medication",
    accent:
      "text-indigo-600 dark:text-indigo-400 bg-indigo-500/10 border-indigo-500/20",
  },
  lab: {
    icon: FlaskConical,
    label: "Lab result",
    accent:
      "text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
  },
  history: {
    icon: History,
    label: "History",
    accent:
      "text-amber-600 dark:text-amber-400 bg-amber-500/10 border-amber-500/20",
  },
  nlp: {
    icon: FileText,
    label: "Clinical note",
    accent:
      "text-sky-600 dark:text-sky-400 bg-sky-500/10 border-sky-500/20",
  },
  note: {
    icon: FileText,
    label: "Clinical note",
    accent:
      "text-sky-600 dark:text-sky-400 bg-sky-500/10 border-sky-500/20",
  },
  other: {
    icon: FileText,
    label: "Other",
    accent: "text-muted-foreground bg-muted border-border",
  },
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ConfidenceHero({ pct }: { pct: number }) {
  const tier = confidenceTier(pct);

  return (
    <div className={cn("rounded-xl border bg-card p-4 ring-1", tier.ring)}>
      <div className="flex items-baseline justify-between gap-3">
        <div className="flex items-center gap-1.5">
          <span
            className={cn(
              "text-xs font-semibold uppercase tracking-wider",
              tier.text,
            )}
          >
            {tier.label}
          </span>
          <TooltipProvider delay={150}>
            <Tooltip>
              <TooltipTrigger
                render={<button type="button" />}
                className="inline-flex h-4 w-4 items-center justify-center rounded-full text-muted-foreground/70 transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                aria-label="How is confidence calculated?"
              >
                <Info className="h-3 w-3" aria-hidden />
              </TooltipTrigger>
              <TooltipContent
                side="bottom"
                align="start"
                className="max-w-xs whitespace-normal text-xs leading-relaxed"
              >
                {CONFIDENCE_METHODOLOGY}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
        <span className="text-2xl font-bold tabular-nums leading-none">
          {pct}
          <span className="ml-0.5 text-sm font-medium text-muted-foreground">
            %
          </span>
        </span>
      </div>
      <div
        className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Confidence ${pct}%`}
      >
        <div
          className={cn(
            "h-full rounded-full transition-all duration-500",
            tier.bar,
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

/**
 * [M][E][A][T] letter indicator row.
 * Green = found, gray = missing. No circular gauge.
 */
function MeatIndicators({ meat }: { meat: SuspectMeat }) {
  const letters: { key: keyof SuspectMeat; label: string; title: string }[] = [
    { key: "monitor", label: "M", title: "Monitor" },
    { key: "evaluate", label: "E", title: "Evaluate" },
    { key: "assess", label: "A", title: "Assess" },
    { key: "treat", label: "T", title: "Treat" },
  ];

  const foundCount = letters.filter(({ key }) => Boolean(meat[key])).length;

  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          MEAT documentation
        </p>
        <span className="text-[11px] tabular-nums text-muted-foreground/70">
          {foundCount} / 4
        </span>
      </div>
      <div
        className="flex items-end gap-3"
        role="list"
        aria-label="MEAT documentation status"
      >
        {letters.map(({ key, label, title }) => {
          const present = Boolean(meat[key]);
          return (
            <div
              key={key}
              role="listitem"
              className="flex flex-col items-center gap-1"
            >
              <span
                title={`${title}: ${present ? "documented" : "not documented"}`}
                aria-label={`${title}: ${present ? "documented" : "not documented"}`}
                className={cn(
                  "inline-flex h-9 w-9 items-center justify-center rounded-lg text-sm font-bold border select-none",
                  present
                    ? "bg-emerald-50 dark:bg-emerald-950/50 text-emerald-700 dark:text-emerald-300 border-emerald-300 dark:border-emerald-700"
                    : "bg-muted/40 text-muted-foreground/35 border-muted",
                )}
              >
                {label}
              </span>
              <span
                className={cn(
                  "text-[9px] font-medium uppercase tracking-wide",
                  present
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-muted-foreground/40",
                )}
              >
                {present ? "found" : "—"}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * Revenue uplift card.
 * Stacked layout, whole-dollar amounts, no cents.
 */
function UpliftCard({ dollarImpact }: { dollarImpact: number }) {
  const perYear = Math.round(dollarImpact);
  const perMonth = Math.round(dollarImpact / 12);

  return (
    <div className="rounded-xl border bg-card p-4">
      <p className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        Revenue impact
      </p>
      <div className="space-y-1.5">
        <div className="flex items-baseline gap-1.5">
          <span className="text-xl font-bold tabular-nums text-emerald-600 dark:text-emerald-400">
            +${perYear.toLocaleString()}
          </span>
          <span className="text-xs text-muted-foreground">/ year</span>
        </div>
        <p className="text-xs text-muted-foreground tabular-nums">
          +${perMonth.toLocaleString()} / month
        </p>
      </div>
    </div>
  );
}

function SignalCard({ sig }: { sig: ContributingSignal }) {
  const meta = SOURCE_META[sig.source] ?? SOURCE_META.other;
  const Icon = meta.icon;

  // Humanize the label — fall back gracefully if it's a raw type key.
  const displayLabel = (() => {
    if (!sig.label) return "Supporting evidence found";
    // If the label looks like a raw snake_case key (no spaces, contains _)
    // and matches the source type, humanize it. Otherwise use as-is.
    if (sig.label === sig.source || sig.label.match(/^[a-z_]+$/) && !sig.label.includes(" ")) {
      return humanizeEvidence(sig.label);
    }
    return sig.label;
  })();

  return (
    <li className="rounded-lg border bg-card p-3 transition-colors hover:border-foreground/20">
      <div className="flex items-start gap-3">
        <span
          className={cn(
            "flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-md border",
            meta.accent,
          )}
          aria-hidden
        >
          <Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              {meta.label}
            </span>
            {sig.timestamp && (
              <span className="text-[11px] tabular-nums text-muted-foreground/70">
                {sig.timestamp}
              </span>
            )}
          </div>
          <p className="break-words text-sm font-medium leading-snug">
            {displayLabel}
          </p>
          {sig.value && (
            <p className="break-words text-xs leading-relaxed text-muted-foreground">
              {sig.value}
            </p>
          )}
        </div>
      </div>
    </li>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-4" aria-hidden>
      <div className="flex gap-2">
        <div className="skeleton h-5 w-16 rounded-full" />
        <div className="skeleton h-5 w-14 rounded-full" />
      </div>
      <div className="skeleton h-24 rounded-xl" />
      <div className="skeleton h-16 rounded-lg" />
      <div className="space-y-2">
        <div className="skeleton h-20 rounded-lg" />
        <div className="skeleton h-20 rounded-lg" />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Rich Evidence Detail — type-specific cards
// ---------------------------------------------------------------------------

/** Helper: extract a value from evidence blob with multiple possible keys */
function evGet(blob: Record<string, unknown>, ...keys: string[]): unknown {
  for (const k of keys) {
    if (blob[k] != null && blob[k] !== "") return blob[k];
  }
  return undefined;
}

/** Format a confidence number (0-1 or 0-100) consistently as percentage */
function fmtConf(val: unknown): string | null {
  if (val == null) return null;
  const n = Number(val);
  if (isNaN(n)) return null;
  // If > 1, treat as already percentage
  const pct = n > 1 ? n : n * 100;
  return `${pct.toFixed(0)}%`;
}

function MedicationEvidence({ ev }: { ev: Record<string, unknown> }) {
  const drug = evGet(ev, "drug", "medication", "drug_name", "label") as string | undefined;
  const matchType = evGet(ev, "match_type", "match") as string | undefined;
  const signalId = evGet(ev, "medication_signal_id", "signal_id") as number | undefined;
  const drugClass = evGet(ev, "signal_drug_class", "drug_class", "atc_class") as string | undefined;
  const description = evGet(ev, "signal_description", "description", "rationale") as string | undefined;
  const confBase = evGet(ev, "confidence_base", "base_confidence") as number | undefined;

  return (
    <div className="space-y-2">
      {drug && (
        <div className="flex items-start gap-2">
          <Pill className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-indigo-500" aria-hidden />
          <p className="text-sm">
            <span className="font-medium">Drug Match:</span>{" "}
            <span className="font-semibold">{drug}</span>
            {matchType && (
              <span className="ml-1 text-muted-foreground">({matchType.replace(/_/g, " ")})</span>
            )}
          </p>
        </div>
      )}
      {signalId != null && (
        <div className="flex items-start gap-2">
          <Hash className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" aria-hidden />
          <p className="text-sm text-muted-foreground">
            Signal Rule: #{signalId}
            {drugClass && <span> — drug_class: {drugClass}</span>}
          </p>
        </div>
      )}
      {confBase != null && (
        <div className="flex items-start gap-2">
          <TrendingUp className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" aria-hidden />
          <p className="text-sm text-muted-foreground">
            Base Confidence: {fmtConf(confBase) ?? String(confBase)}
          </p>
        </div>
      )}
      {description && (
        <div className="flex items-start gap-2">
          <FileText className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" aria-hidden />
          <p className="text-sm italic text-muted-foreground">{description}</p>
        </div>
      )}
    </div>
  );
}

function LabEvidence({ ev }: { ev: Record<string, unknown> }) {
  const testName = evGet(ev, "test", "lab_name", "label", "name") as string | undefined;
  const value = evGet(ev, "value", "result", "lab_value") as string | number | undefined;
  const unit = evGet(ev, "unit", "units") as string | undefined;
  const threshold = evGet(ev, "threshold_expression", "threshold", "interpretation") as string | undefined;
  const signalId = evGet(ev, "lab_signal_id", "signal_id") as number | undefined;
  const loinc = evGet(ev, "signal_loinc_code", "loinc", "loinc_code") as string | undefined;
  const confBase = evGet(ev, "confidence_base", "base_confidence") as number | undefined;

  return (
    <div className="space-y-2">
      {(testName || value != null) && (
        <div className="flex items-start gap-2">
          <FlaskConical className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-emerald-500" aria-hidden />
          <p className="text-sm">
            <span className="font-medium">Lab Result:</span>{" "}
            {testName && <span className="font-semibold">{testName}</span>}
            {value != null && (
              <span className="ml-1 tabular-nums font-semibold">
                {value}{unit ? ` ${unit}` : ""}
              </span>
            )}
          </p>
        </div>
      )}
      {threshold && (
        <div className="flex items-start gap-2">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-amber-500" aria-hidden />
          <p className="text-sm">
            <span className="font-medium">Threshold:</span>{" "}
            <span className="text-muted-foreground">{threshold}</span>
          </p>
        </div>
      )}
      {signalId != null && (
        <div className="flex items-start gap-2">
          <Hash className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" aria-hidden />
          <p className="text-sm text-muted-foreground">
            Signal Rule: #{signalId}
            {loinc && <span> — LOINC: {loinc}</span>}
          </p>
        </div>
      )}
      {confBase != null && (
        <div className="flex items-start gap-2">
          <TrendingUp className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" aria-hidden />
          <p className="text-sm text-muted-foreground">
            Base Confidence: {fmtConf(confBase) ?? String(confBase)}
          </p>
        </div>
      )}
    </div>
  );
}

function ComorbidityEvidence({ ev }: { ev: Record<string, unknown> }) {
  const patternName = evGet(ev, "pattern_name", "name", "label") as string | undefined;
  const patternId = evGet(ev, "comorbidity_pattern_id", "pattern_id") as number | undefined;
  const conditionA = evGet(ev, "condition_a", "condition_a_icd10") as string | undefined;
  const conditionB = evGet(ev, "condition_b", "condition_b_icd10") as string | undefined;
  const conditionALabel = evGet(ev, "condition_a_label") as string | undefined;
  const conditionBLabel = evGet(ev, "condition_b_label") as string | undefined;
  const matchedA = evGet(ev, "matched_a", "matched_condition_a") as string | undefined;
  const matchedB = evGet(ev, "matched_b", "matched_condition_b") as string | undefined;
  const rationale = evGet(ev, "clinical_rationale", "rationale", "description") as string | undefined;
  const confBase = evGet(ev, "confidence_base", "base_confidence") as number | undefined;

  return (
    <div className="space-y-2">
      {patternName && (
        <div className="flex items-start gap-2">
          <Link2 className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-violet-500" aria-hidden />
          <p className="text-sm">
            <span className="font-medium">Comorbidity Pattern:</span>{" "}
            <span className="font-semibold">&ldquo;{patternName}&rdquo;</span>
          </p>
        </div>
      )}
      {(conditionA || conditionB) && (
        <div className="ml-5 space-y-1 rounded-md border border-border/50 bg-muted/30 px-3 py-2 text-xs">
          {conditionA && (
            <p>
              <span className="font-medium text-muted-foreground">Condition A:</span>{" "}
              {conditionA}{conditionALabel ? ` (${conditionALabel})` : ""}
              {matchedA && <span className="text-emerald-600 dark:text-emerald-400"> — matched {matchedA}</span>}
            </p>
          )}
          {conditionB && (
            <p>
              <span className="font-medium text-muted-foreground">Condition B:</span>{" "}
              {conditionB}{conditionBLabel ? ` (${conditionBLabel})` : ""}
              {matchedB && <span className="text-emerald-600 dark:text-emerald-400"> — matched {matchedB}</span>}
            </p>
          )}
        </div>
      )}
      {patternId != null && (
        <div className="flex items-start gap-2">
          <Hash className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" aria-hidden />
          <p className="text-sm text-muted-foreground">Pattern Rule: #{patternId}</p>
        </div>
      )}
      {confBase != null && (
        <div className="flex items-start gap-2">
          <TrendingUp className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" aria-hidden />
          <p className="text-sm text-muted-foreground">
            Base Confidence: {fmtConf(confBase) ?? String(confBase)}
          </p>
        </div>
      )}
      {rationale && (
        <div className="flex items-start gap-2">
          <FileText className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" aria-hidden />
          <p className="text-sm italic text-muted-foreground">{rationale}</p>
        </div>
      )}
    </div>
  );
}

function SpecificityEvidence({ ev }: { ev: Record<string, unknown> }) {
  const genericIcd = evGet(ev, "generic_icd10", "current_icd10", "from_icd10") as string | undefined;
  const genericLabel = evGet(ev, "generic_label", "current_label") as string | undefined;
  const specificIcd = evGet(ev, "specific_icd10", "suggested_icd10", "to_icd10") as string | undefined;
  const specificLabel = evGet(ev, "specific_label", "suggested_label") as string | undefined;
  const currentHcc = evGet(ev, "current_hcc", "from_hcc") as string | undefined;
  const suggestedHcc = evGet(ev, "suggested_hcc", "to_hcc") as string | undefined;
  const supportingEvidence = evGet(ev, "supporting_evidence", "evidence_note") as string | undefined;
  const revenueDelta = evGet(ev, "revenue_delta_est", "revenue_delta", "dollar_impact") as number | undefined;
  const upgradeId = evGet(ev, "specificity_upgrade_id", "upgrade_id") as number | undefined;

  return (
    <div className="space-y-2">
      <div className="flex items-start gap-2">
        <TrendingUp className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-sky-500" aria-hidden />
        <p className="text-sm font-medium">Code Upgrade Opportunity</p>
      </div>
      <div className="ml-5 space-y-1.5 rounded-md border border-border/50 bg-muted/30 px-3 py-2 text-xs">
        {genericIcd && (
          <div className="flex items-center gap-1.5">
            <span className="font-medium text-muted-foreground">Current:</span>
            <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">{genericIcd}</code>
            {genericLabel && <span className="text-muted-foreground">({genericLabel})</span>}
            {currentHcc && <span className="text-muted-foreground/70">HCC {currentHcc}</span>}
          </div>
        )}
        {specificIcd && (
          <div className="flex items-center gap-1.5">
            <span className="font-medium text-emerald-600 dark:text-emerald-400">Suggested:</span>
            <code className="rounded bg-emerald-50 dark:bg-emerald-950/40 px-1 py-0.5 font-mono text-[11px] text-emerald-700 dark:text-emerald-300">{specificIcd}</code>
            {specificLabel && <span className="text-muted-foreground">({specificLabel})</span>}
            {suggestedHcc && <span className="text-emerald-600 dark:text-emerald-400">HCC {suggestedHcc}</span>}
          </div>
        )}
        {supportingEvidence && (
          <p className="mt-1 text-muted-foreground">Evidence: {supportingEvidence}</p>
        )}
      </div>
      {revenueDelta != null && revenueDelta > 0 && (
        <div className="flex items-start gap-2">
          <DollarSign className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-emerald-500" aria-hidden />
          <p className="text-sm font-semibold text-emerald-600 dark:text-emerald-400">
            Estimated Revenue Impact: +${Math.round(revenueDelta).toLocaleString()}/year
          </p>
        </div>
      )}
      {upgradeId != null && (
        <div className="flex items-start gap-2">
          <Hash className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" aria-hidden />
          <p className="text-sm text-muted-foreground">Upgrade Rule: #{upgradeId}</p>
        </div>
      )}
    </div>
  );
}

function HistoricalEvidence({ ev }: { ev: Record<string, unknown> }) {
  const priorYear = evGet(ev, "prior_year", "year", "source_year") as number | string | undefined;
  const priorHcc = evGet(ev, "prior_hcc", "hcc", "prior_hcc_code") as string | undefined;
  const priorHccLabel = evGet(ev, "prior_hcc_label", "hcc_label", "label") as string | undefined;
  const priorIcd10 = evGet(ev, "prior_icd10", "icd10", "source_icd10") as string | undefined;
  const priorCoeff = evGet(ev, "prior_raf_coefficient", "raf_coefficient", "coefficient") as number | undefined;
  const priorEncounterIds = evGet(ev, "prior_source_encounter_ids", "encounter_ids") as number[] | undefined;
  const priorHccId = evGet(ev, "prior_hcc_id", "hcc_id") as number | undefined;

  return (
    <div className="space-y-2">
      <div className="flex items-start gap-2">
        <Calendar className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-amber-500" aria-hidden />
        <p className="text-sm font-medium">Recapture Gap</p>
      </div>
      <div className="ml-5 space-y-1 rounded-md border border-amber-200 dark:border-amber-800/50 bg-amber-50/50 dark:bg-amber-950/20 px-3 py-2 text-xs">
        {priorYear && (
          <p>
            <span className="font-medium text-muted-foreground">Prior Year:</span>{" "}
            {priorYear}
            {priorHcc && <span> — HCC {priorHcc}</span>}
            {priorHccLabel && <span> ({priorHccLabel})</span>}
            {priorIcd10 && <span> coded via {priorIcd10}</span>}
          </p>
        )}
        <p>
          <span className="font-medium text-amber-700 dark:text-amber-400">Current Year:</span>{" "}
          Not yet recaptured
        </p>
        {priorCoeff != null && (
          <p>
            <span className="font-medium text-muted-foreground">Prior RAF Coefficient:</span>{" "}
            <span className="tabular-nums font-semibold">{Number(priorCoeff).toFixed(3)}</span>
          </p>
        )}
        {priorEncounterIds && priorEncounterIds.length > 0 && (
          <p className="text-muted-foreground">
            Source encounters: {priorEncounterIds.join(", ")}
          </p>
        )}
      </div>
      <div className="flex items-start gap-2">
        <Info className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" aria-hidden />
        <p className="text-xs text-muted-foreground">
          Annual re-documentation required for CMS risk adjustment
        </p>
      </div>
      {priorHccId != null && (
        <div className="flex items-start gap-2">
          <Hash className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" aria-hidden />
          <p className="text-sm text-muted-foreground">Prior HCC record: #{priorHccId}</p>
        </div>
      )}
    </div>
  );
}

function NLPEvidence({ ev }: { ev: Record<string, unknown> }) {
  const sentence = evGet(ev, "nlp_evidence_sentence", "sentence", "text", "snippet", "excerpt") as string | undefined;
  const start = evGet(ev, "nlp_evidence_start", "start", "char_start") as number | undefined;
  const end = evGet(ev, "nlp_evidence_end", "end", "char_end") as number | undefined;
  const encounterDate = evGet(ev, "encounter_date", "date", "source_date") as string | undefined;
  const model = evGet(ev, "model", "nlp_model", "extractor") as string | undefined;
  const verified = evGet(ev, "verified", "quote_verified") as boolean | undefined;

  // Render the sentence with the matched portion highlighted if offsets given
  const renderSentence = () => {
    if (!sentence) return null;
    if (start != null && end != null && start < end && end <= sentence.length) {
      const before = sentence.slice(0, start);
      const matched = sentence.slice(start, end);
      const after = sentence.slice(end);
      return (
        <p className="text-sm leading-relaxed">
          {before && <span className="text-muted-foreground">{before}</span>}
          <mark className="rounded bg-sky-100 px-0.5 font-medium text-sky-900 dark:bg-sky-900/40 dark:text-sky-200">
            {matched}
          </mark>
          {after && <span className="text-muted-foreground">{after}</span>}
        </p>
      );
    }
    return (
      <p className="text-sm font-medium leading-relaxed italic">
        &ldquo;{sentence}&rdquo;
      </p>
    );
  };

  return (
    <div className="space-y-2">
      <div className="flex items-start gap-2">
        <FileText className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-sky-500" aria-hidden />
        <p className="text-sm font-medium">Clinical Note Evidence</p>
      </div>
      {sentence && (
        <div className="ml-5 rounded-md border border-sky-200 dark:border-sky-800/50 bg-sky-50/50 dark:bg-sky-950/20 px-3 py-2">
          {renderSentence()}
        </div>
      )}
      <div className="ml-5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {encounterDate && (
          <span className="flex items-center gap-1">
            <Calendar className="h-3 w-3" aria-hidden />
            {encounterDate}
          </span>
        )}
        {model && (
          <span className="flex items-center gap-1">
            <Sparkles className="h-3 w-3" aria-hidden />
            {model}
          </span>
        )}
        {verified && (
          <span className="flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
            <Check className="h-3 w-3" aria-hidden />
            Quote verified
          </span>
        )}
      </div>
    </div>
  );
}

/** Confidence breakdown showing base + adjustments */
function ConfidenceBreakdown({ ev }: { ev: Record<string, unknown> }) {
  const confBase = evGet(ev, "confidence_base", "base_confidence") as number | undefined;
  const dampening = evGet(ev, "context_dampening", "dampening_factor", "historical_dampening") as number | undefined;
  const finalConf = evGet(ev, "confidence", "confidence_score", "final_confidence") as number | undefined;

  if (confBase == null) return null;

  return (
    <div className="mt-2 rounded-md border border-border/50 bg-muted/30 px-3 py-2 text-xs space-y-0.5">
      <p className="font-medium text-muted-foreground">Confidence Breakdown</p>
      <p className="tabular-nums">
        Base: {fmtConf(confBase)} <span className="text-muted-foreground">(signal rule)</span>
      </p>
      {dampening != null && dampening !== 1 && (
        <p className="tabular-nums">
          x {(dampening > 1 ? dampening / 100 : dampening).toFixed(2)}{" "}
          <span className="text-muted-foreground">(historical context dampening)</span>
        </p>
      )}
      {finalConf != null && dampening != null && (
        <p className="tabular-nums font-medium">
          = {fmtConf(finalConf)}
        </p>
      )}
    </div>
  );
}

/**
 * Determines the evidence source type from the raw blob and renders the
 * appropriate rich evidence card. Falls back gracefully when fields are missing.
 */
function RichEvidenceDetail({ evidenceRaw, evidenceType }: {
  evidenceRaw: Record<string, unknown> | unknown[] | null | undefined;
  evidenceType: string;
}) {
  if (!evidenceRaw) return null;

  // Normalise: if array, take first element; must be a dict for rich rendering
  const blob: Record<string, unknown> | null = (() => {
    if (Array.isArray(evidenceRaw)) {
      const first = evidenceRaw[0];
      return first && typeof first === "object" && !Array.isArray(first)
        ? (first as Record<string, unknown>)
        : null;
    }
    if (typeof evidenceRaw === "object") return evidenceRaw as Record<string, unknown>;
    return null;
  })();

  if (!blob) return null;

  // Determine source from the blob or fall back to the evidence_type string
  const source = (() => {
    const raw = (blob.source ?? blob.evidence_source ?? blob.scan_type ?? "") as string;
    if (raw) return raw.toLowerCase();
    const et = evidenceType.toLowerCase();
    if (et.startsWith("med") || et.includes("drug")) return "medication";
    if (et.startsWith("lab")) return "lab";
    if (et.includes("comorbid") || et.includes("pattern")) return "comorbidity";
    if (et.includes("specific") || et.includes("upgrade")) return "specificity_upgrade";
    if (et.startsWith("hist") || et.startsWith("recap")) return "historical";
    if (et.startsWith("nlp") || et.startsWith("note")) return "nlp";
    return "";
  })();

  // Check if the blob has enough rich fields to warrant a type-specific card
  const hasMedFields = blob.medication_signal_id != null || blob.drug != null || blob.medication != null || blob.drug_name != null || blob.signal_drug_class != null;
  const hasLabFields = blob.lab_signal_id != null || blob.threshold_expression != null || blob.signal_loinc_code != null;
  const hasComorbidFields = blob.comorbidity_pattern_id != null || blob.pattern_name != null;
  const hasSpecificityFields = blob.specificity_upgrade_id != null || blob.generic_icd10 != null || blob.specific_icd10 != null;
  const hasHistFields = blob.prior_hcc_id != null || blob.prior_raf_coefficient != null || blob.prior_source_encounter_ids != null;
  const hasNlpFields = blob.nlp_evidence_sentence != null || blob.sentence != null || blob.snippet != null || blob.excerpt != null;

  const renderCard = () => {
    // Source-based routing with field presence fallbacks
    if (source === "medication" || hasMedFields) return <MedicationEvidence ev={blob} />;
    if (source === "lab" || hasLabFields) return <LabEvidence ev={blob} />;
    if (source === "comorbidity" || source === "comorbidity_pattern" || hasComorbidFields) return <ComorbidityEvidence ev={blob} />;
    if (source === "specificity_upgrade" || source === "specificity" || hasSpecificityFields) return <SpecificityEvidence ev={blob} />;
    if (source === "historical" || source === "history" || source === "recapture" || hasHistFields) return <HistoricalEvidence ev={blob} />;
    if (source === "nlp" || source === "note_nlp" || source === "note" || hasNlpFields) return <NLPEvidence ev={blob} />;
    // No matching source or fields — skip rich rendering
    return null;
  };

  const card = renderCard();
  if (!card) return null;

  return (
    <div className="rounded-xl border bg-card p-4">
      <p className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        Evidence attribution
      </p>
      {card}
      <ConfidenceBreakdown ev={blob} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function ExplainPanel({
  patientId,
  suspectId,
  suspectLabel,
  open,
  onClose,
  onAccept,
  onRequestDismiss,
  busy = null,
  suspectMeat,
  suspectDollarImpact,
}: ExplainPanelProps) {
  const [mounted, setMounted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<ExplainResponse | null>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .get<ExplainResponse>(
        `/api/raf-central/${patientId}/suspect/${suspectId}/explain`,
      )
      .then((r) => {
        if (!cancelled) setData(r.data);
      })
      .catch((e) => {
        if (!cancelled)
          setError(
            e?.response?.data?.detail ||
              e?.message ||
              "Failed to load evidence",
          );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, patientId, suspectId]);

  useEffect(() => {
    if (open) {
      previouslyFocusedRef.current = document.activeElement as HTMLElement;
    } else {
      previouslyFocusedRef.current?.focus();
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener("keydown", handleKeyDown, true);
    return () => document.removeEventListener("keydown", handleKeyDown, true);
  }, [open, onClose]);

  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  if (!open || !mounted) return null;

  const confPct = data ? Math.round(data.confidence * 100) : null;
  const showFooter = Boolean(onAccept || onRequestDismiss);
  const footerDisabled = busy !== null || loading;

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] animate-in fade-in bg-black/40 duration-150"
      onClick={onClose}
      aria-hidden="true"
    >
      <FocusTrap enabled restoreFocus={false}>
        {/*
          Max-width 420px per design spec. The full-height right-anchored
          drawer sits on top of a semi-transparent backdrop that handles
          click-away to close — main content is visible but dimmed behind it.
        */}
        <div
          className="absolute right-0 top-0 flex h-full w-full animate-in slide-in-from-right flex-col border-l shadow-2xl duration-200 glass-frosted"
          style={{ maxWidth: 420 }}
          onClick={(e) => e.stopPropagation()}
          role="dialog"
          aria-modal="true"
          aria-label={`Evidence for ${suspectLabel}`}
        >
          {/* ── Header ─────────────────────────────────────────────── */}
          <header className="flex-shrink-0 border-b border-white/20 dark:border-white/10 bg-white/60 dark:bg-slate-900/60 backdrop-blur-sm">
            <div className="flex items-start justify-between gap-3 px-5 pt-4 pb-3">
              <div className="min-w-0 flex-1">
                <div className="mb-1 flex items-center gap-1.5 text-primary">
                  <Sparkles className="h-3.5 w-3.5" aria-hidden />
                  <span className="text-[11px] font-semibold uppercase tracking-wider">
                    Why was this flagged?
                  </span>
                </div>
                <h2 className="text-base font-bold leading-snug">
                  {suspectLabel}
                </h2>
                {data && (
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    <Badge variant="secondary" className="font-semibold">
                      HCC {data.suspect_hcc}
                    </Badge>
                    <Badge variant="outline" className="font-mono">
                      {data.suspect_icd10}
                    </Badge>
                    {data.evidence_type && (
                      <Badge
                        variant="ghost"
                        className="text-muted-foreground capitalize"
                      >
                        {humanizeEvidence(data.evidence_type)}
                      </Badge>
                    )}
                  </div>
                )}
              </div>
              <Button
                size="icon"
                variant="ghost"
                className="-mr-2 -mt-1 h-8 w-8 flex-shrink-0 rounded-full"
                aria-label="Close evidence panel (Esc)"
                onClick={onClose}
                title="Close (Esc)"
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          </header>

          {/* ── Scrollable body ─────────────────────────────────────── */}
          <div
            className="flex-1 overflow-y-auto"
            aria-live="polite"
            aria-busy={loading}
          >
            <div className="space-y-4 p-5">
              {loading && <LoadingSkeleton />}

              {error && (
                <div
                  className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
                  role="alert"
                >
                  <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
                  <div className="space-y-1">
                    <p className="font-medium">Couldn&apos;t load evidence</p>
                    <p className="text-xs opacity-90">{error}</p>
                  </div>
                </div>
              )}

              {!loading && !error && data && (
                <>
                  {/* ── Stale-evidence banner ─────────────────────────── */}
                  {(() => {
                    if (!data.evidence_date) return null;
                    const ageMs =
                      Date.now() - new Date(data.evidence_date).getTime();
                    const ageMonths = ageMs / (1000 * 60 * 60 * 24 * 30.44);
                    if (ageMonths <= 6) return null;
                    const ageRounded = Math.round(ageMonths);
                    return (
                      <div
                        role="alert"
                        className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2.5 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/60 dark:text-amber-300"
                      >
                        <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" aria-hidden />
                        <span>
                          Evidence is{" "}
                          <span className="font-semibold">
                            {ageRounded} month{ageRounded !== 1 ? "s" : ""} old
                          </span>{" "}
                          — consider refreshing before attestation.
                        </span>
                      </div>
                    );
                  })()}

                  {/* ── Context-classification warning banner ─────────── */}
                  {data.context_classification &&
                    data.context_classification !== "positive" && (
                      <div
                        role="alert"
                        className="flex items-start gap-2 rounded-lg border border-pink-300 bg-pink-50 px-3 py-2.5 text-sm text-pink-800 dark:border-pink-800/60 dark:bg-pink-950/50 dark:text-pink-300"
                      >
                        <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" aria-hidden />
                        <span>
                          This evidence was classified as{" "}
                          <span className="font-semibold capitalize">
                            {data.context_classification}
                          </span>{" "}
                          in the source note. Accepting may expose the practice
                          to RADV risk.
                        </span>
                      </div>
                    )}

                  {/* ── Confidence hero ───────────────────────────────── */}
                  {confPct !== null && <ConfidenceHero pct={confPct} />}

                  {/* ── Summary ──────────────────────────────────────── */}
                  {data.summary && (
                    <div className="rounded-lg border-l-2 border-primary/40 bg-muted px-4 py-3">
                      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                        Summary
                      </p>
                      <p className="text-sm leading-relaxed text-foreground">
                        {data.summary}
                      </p>
                    </div>
                  )}

                  {/* ── Rich evidence attribution (type-specific) ──────── */}
                  <RichEvidenceDetail
                    evidenceRaw={data.evidence_detail_raw}
                    evidenceType={data.evidence_type}
                  />

                  {/* ── Revenue uplift (from SuspectCard prop) ────────── */}
                  {suspectDollarImpact != null && suspectDollarImpact > 0 && (
                    <UpliftCard dollarImpact={suspectDollarImpact} />
                  )}

                  {/* ── MEAT [M][E][A][T] indicators ─────────────────── */}
                  {suspectMeat != null && (
                    <MeatIndicators meat={suspectMeat} />
                  )}

                  {/* ── Contributing signals ──────────────────────────── */}
                  <div>
                    <div className="mb-2 flex items-baseline justify-between">
                      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                        Contributing signals
                      </p>
                      {data.contributing_signals.length > 0 && (
                        <span className="text-[11px] tabular-nums text-muted-foreground/70">
                          {data.contributing_signals.length} found
                        </span>
                      )}
                    </div>
                    {data.contributing_signals.length === 0 ? (
                      <div className="rounded-lg border border-dashed bg-muted/20 px-4 py-8 text-center">
                        <div className="mx-auto mb-2 flex h-10 w-10 items-center justify-center rounded-full bg-muted">
                          <FileText className="h-5 w-5 text-muted-foreground" />
                        </div>
                        <p className="text-sm font-medium text-foreground">
                          No supporting signals linked
                        </p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          This suspect was flagged from header-level evidence
                          only.
                        </p>
                      </div>
                    ) : (
                      <ul className="space-y-2">
                        {data.contributing_signals.map((sig, i) => (
                          <SignalCard key={i} sig={sig} />
                        ))}
                      </ul>
                    )}
                  </div>

                  {/* ── Clinical-rule adjustments ─────────────────────── */}
                  {data.clinical_rule_adjustments &&
                    data.clinical_rule_adjustments.length > 0 && (
                      <div>
                        <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                          Clinical-rule adjustments
                        </p>
                        <ul className="space-y-2">
                          {data.clinical_rule_adjustments.map((adj) => {
                            const deltaPct = Math.round(
                              Math.abs(adj.confidence_delta) * 100,
                            );
                            const sign = adj.confidence_delta < 0 ? "−" : "+";
                            return (
                              <li
                                key={adj.rule_id}
                                className="rounded-lg border border-amber-200 bg-amber-50/60 p-3 dark:border-amber-800/50 dark:bg-amber-950/30"
                              >
                                <p className="text-xs font-semibold text-amber-900 dark:text-amber-300">
                                  {adj.rule_name}
                                </p>
                                <p className="mt-0.5 text-sm leading-snug text-foreground">
                                  {adj.explanation}
                                </p>
                                <p className="mt-1 text-[11px] font-medium tabular-nums text-amber-700 dark:text-amber-400">
                                  {sign}
                                  {deltaPct}% confidence
                                </p>
                              </li>
                            );
                          })}
                        </ul>
                      </div>
                    )}
                </>
              )}
            </div>
          </div>

          {/* ── Footer ─────────────────────────────────────────────── */}
          {showFooter && !error && (
            <footer className="flex-shrink-0 border-t border-white/20 dark:border-white/10 bg-white/60 dark:bg-slate-900/60 backdrop-blur-sm px-5 py-3">
              <div className="flex items-center gap-2">
                {onRequestDismiss && (
                  <Button
                    variant="outline"
                    className="flex-1"
                    onClick={onRequestDismiss}
                    disabled={footerDisabled}
                  >
                    {busy === "dismiss" ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <>
                        <XCircle className="mr-1.5 h-4 w-4" aria-hidden />
                        Dismiss
                      </>
                    )}
                  </Button>
                )}
                {onAccept && (() => {
                  // Hard gate: disable Accept entirely when the source-note
                  // context classification flags this evidence as
                  // negated/family-history/hypothetical — these are the
                  // four RADV "killers" that cannot be billed even with a
                  // clinician override. Banner alone is not a safety
                  // control (patient-safety review #3 / round-3 #C).
                  const blockedContexts = new Set([
                    "negated",
                    "family",
                    "hypothetical",
                    "resolved",
                  ]);
                  const ctx = (data?.context_classification ?? "").toLowerCase();
                  const contextBlocked = blockedContexts.has(ctx);
                  return (
                    <Button
                      className="flex-1"
                      onClick={() => void onAccept()}
                      disabled={footerDisabled || contextBlocked}
                      title={
                        contextBlocked
                          ? `Accept disabled — source note classifies this evidence as ${ctx}. RADV-uncodeable.`
                          : undefined
                      }
                    >
                      {busy === "accept" ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <>
                          <Check className="mr-1.5 h-4 w-4" aria-hidden />
                          {contextBlocked ? "Accept blocked" : "Accept"}
                        </>
                      )}
                    </Button>
                  );
                })()}
              </div>
              <p className="mt-2 text-center text-[11px] text-muted-foreground/70">
                {loading
                  ? "Loading evidence..."
                  : busy
                  ? "Saving..."
                  : "Press Esc to close"}
              </p>
            </footer>
          )}
        </div>
      </FocusTrap>
    </div>,
    document.body,
  );
}

export default ExplainPanel;
