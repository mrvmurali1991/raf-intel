/**
 * Single source of truth for suspect-condition confidence tiers.
 *
 * The confidence score is a 0-1 probability emitted by the RAF suspect engine
 * (see backend/app/services/suspect_engine.py). Thresholds live ONLY here so
 * UI surfaces cannot drift.
 */

export type ConfidenceTone = "high" | "moderate" | "low";

export const CONFIDENCE_HIGH_MIN = 85;
export const CONFIDENCE_MODERATE_MIN = 70;

export interface ConfidenceTier {
  tone: ConfidenceTone;
  label: string;
  /** Tailwind ring utility, e.g. "ring-emerald-500/25". */
  ring: string;
  /** Tailwind bar utility, e.g. "bg-emerald-500". */
  bar: string;
  /** Tailwind text utility, e.g. "text-emerald-600 dark:text-emerald-400". */
  text: string;
  /** Tailwind color name used by components that need to parametrize gauges. */
  color: "emerald" | "amber" | "red";
}

export function confidenceTier(pct: number): ConfidenceTier {
  if (pct >= CONFIDENCE_HIGH_MIN) {
    return {
      tone: "high",
      label: "High confidence",
      ring: "ring-emerald-500/25",
      bar: "bg-emerald-500",
      text: "text-emerald-600 dark:text-emerald-400",
      color: "emerald",
    };
  }
  if (pct >= CONFIDENCE_MODERATE_MIN) {
    return {
      tone: "moderate",
      label: "Moderate confidence",
      ring: "ring-amber-500/25",
      bar: "bg-amber-500",
      text: "text-amber-600 dark:text-amber-400",
      color: "amber",
    };
  }
  return {
    tone: "low",
    label: "Low confidence",
    ring: "ring-red-500/25",
    bar: "bg-red-500",
    text: "text-red-600 dark:text-red-400",
    color: "red",
  };
}

// ---------------------------------------------------------------------------
// RADV-safety accept gate
// ---------------------------------------------------------------------------

/**
 * MEAT statuses that are considered incomplete for RADV purposes.
 * When a suspect carries one of these, the accept gate must be shown.
 */
export const MEAT_RISKY_STATUSES = new Set([
  "partial",
  "incomplete",
  "unknown",
  "pending_rule_review",
]);

/**
 * Returns true when at least one RADV risk condition is present for a suspect.
 * All arguments are nullable / optional so callers need not guard individually.
 *
 * @param confidence  0-1 float (or null)
 * @param meat_status backend meat_status string (or undefined/null)
 * @param clinical_rule_violation truthy when the engine flagged a rule violation
 */
export function needsAcceptGate(
  confidence: number | null | undefined,
  meat_status: string | null | undefined,
  clinical_rule_violation: boolean | string | null | undefined
): boolean {
  if (confidence != null && confidence * 100 < CONFIDENCE_MODERATE_MIN) return true;
  if (meat_status != null && MEAT_RISKY_STATUSES.has(meat_status)) return true;
  if (clinical_rule_violation) return true;
  return false;
}

/**
 * Plain-language explanation of what the confidence number means. Rendered in
 * the ExplainPanel tooltip so clinicians know what they're affirming when they
 * Accept a suspect. ASCII-only for maximum browser-matrix compatibility.
 */
export const CONFIDENCE_METHODOLOGY =
  `Model-estimated likelihood that this condition is currently active, based on ` +
  `structured evidence (medications, labs, history, clinical notes). ` +
  `${CONFIDENCE_HIGH_MIN}% or higher is High; ` +
  `${CONFIDENCE_MODERATE_MIN}-${CONFIDENCE_HIGH_MIN - 1}% is Moderate; ` +
  `below ${CONFIDENCE_MODERATE_MIN}% is Low. This is a decision aid, not a diagnosis -- ` +
  `clinician review is required before billing.`;
