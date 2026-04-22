"use client";

/**
 * AcceptConfirmDialog
 * -------------------
 * RADV-safety confirmation gate shown before accepting a suspect that carries
 * at least one risk condition (low confidence, incomplete MEAT, or a clinical
 * rule violation).
 *
 * Pattern matches DismissReasonDialog for style / a11y — do NOT merge the two.
 *
 * Usage:
 *   <AcceptConfirmDialog
 *     open={showGate}
 *     onClose={() => setShowGate(false)}
 *     onConfirm={({ override_reason, defense_basis }) => doAccept(...)}
 *     suspect={{ hcc_code: "136", icd10_code: "N18.4", confidence: 0.65,
 *                meat_status: "partial", clinical_rule_violation: true,
 *                expected_dollar_impact: 1200, patient_name: "John Doe" }}
 *   />
 */

import { useEffect, useRef, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { CONFIDENCE_MODERATE_MIN, MEAT_RISKY_STATUSES } from "@/lib/confidence";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AcceptConfirmSuspect {
  hcc_code?: string | number | null;
  icd10_code?: string | null;
  confidence?: number | null;
  /** Agent-G adds this field; handle undefined gracefully. */
  meat_status?: string | null;
  /** Number of present MEAT elements out of 4 — derived from meat_status or
   *  meat object when available. Optional display hint. */
  meat_count?: number | null;
  clinical_rule_violation?: boolean | string | null;
  expected_dollar_impact?: number | null;
  patient_name?: string | null;
}

export interface AcceptOverridePayload {
  override_reason: string;
  defense_basis: string;
}

export interface AcceptConfirmDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: (payload: AcceptOverridePayload) => void;
  suspect: AcceptConfirmSuspect;
}

// ---------------------------------------------------------------------------
// Defense basis options — single source here so Agent-N can mirror them
// ---------------------------------------------------------------------------

export const DEFENSE_BASIS_OPTIONS = [
  "Provider clinical judgment",
  "Additional chart evidence exists",
  "Override for re-billing correction",
  "Other (explain)",
] as const;

export type DefenseBasis = (typeof DEFENSE_BASIS_OPTIONS)[number];

const DEFENSE_BASIS_PLACEHOLDER = "Select RADV defense basis…";
const MIN_REASON_CHARS = 20;

// ---------------------------------------------------------------------------
// Risk list builder
// ---------------------------------------------------------------------------

function buildRisks(s: AcceptConfirmSuspect): string[] {
  const risks: string[] = [];

  if (s.confidence != null && s.confidence * 100 < CONFIDENCE_MODERATE_MIN) {
    const pct = Math.round(s.confidence * 100);
    risks.push(
      `Confidence is ${pct}% (below the ${CONFIDENCE_MODERATE_MIN}% RADV threshold)`
    );
  }

  if (s.meat_status != null && MEAT_RISKY_STATUSES.has(s.meat_status)) {
    const countHint =
      s.meat_count != null ? ` (${s.meat_count}/4 elements present)` : "";
    const statusLabel =
      s.meat_status === "partial"
        ? "incomplete"
        : s.meat_status === "pending_rule_review"
        ? "pending clinical rule review"
        : s.meat_status;
    risks.push(`MEAT evidence is ${statusLabel}${countHint}`);
  }

  if (s.clinical_rule_violation) {
    const detail =
      typeof s.clinical_rule_violation === "string"
        ? s.clinical_rule_violation
        : s.hcc_code
        ? `HCC ${s.hcc_code} clinical rule not satisfied`
        : "Clinical rule violation detected";
    risks.push(detail);
  }

  return risks;
}

// ---------------------------------------------------------------------------
// Inner component (remounted on each open to reset state)
// ---------------------------------------------------------------------------

function AcceptConfirmDialogInner({
  suspect,
  onClose,
  onConfirm,
}: Omit<AcceptConfirmDialogProps, "open">) {
  const [overrideReason, setOverrideReason] = useState("");
  const [defenseBasis, setDefenseBasis] = useState<string>("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-focus textarea when dialog opens
  useEffect(() => {
    requestAnimationFrame(() => textareaRef.current?.focus());
  }, []);

  const risks = buildRisks(suspect);
  const reasonValid = overrideReason.trim().length >= MIN_REASON_CHARS;
  const basisValid = defenseBasis !== "" && defenseBasis !== DEFENSE_BASIS_PLACEHOLDER;
  const canSubmit = reasonValid && basisValid;

  const handleSubmit = () => {
    if (!canSubmit) return;
    onConfirm({
      override_reason: overrideReason.trim(),
      defense_basis: defenseBasis,
    });
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      handleSubmit();
    }
  };

  const suspectLabel = [
    suspect.patient_name,
    suspect.icd10_code,
    suspect.hcc_code != null ? `HCC ${suspect.hcc_code}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const charsLeft = Math.max(0, MIN_REASON_CHARS - overrideReason.trim().length);

  return (
    <DialogContent
      showCloseButton={false}
      className="sm:max-w-md"
      onKeyDown={handleKeyDown}
      aria-describedby="accept-gate-desc"
    >
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          {/* Warning icon inline — no new import */}
          <span
            className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-amber-100 dark:bg-amber-900/40 text-amber-600 dark:text-amber-400 text-xs font-bold shrink-0"
            aria-hidden="true"
          >
            !
          </span>
          Accept with caution
        </DialogTitle>
      </DialogHeader>

      <div className="space-y-4 py-1" id="accept-gate-desc">
        {/* Suspect label */}
        {suspectLabel && (
          <p className="text-xs text-muted-foreground truncate">{suspectLabel}</p>
        )}

        {/* Risk checklist */}
        <div
          className="rounded-md border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 px-3 py-2.5 space-y-1.5"
          role="list"
          aria-label="RADV risk factors"
        >
          <p className="text-xs font-semibold text-amber-700 dark:text-amber-400 mb-1.5">
            Risk factors requiring documentation:
          </p>
          {risks.map((risk, i) => (
            <div
              key={i}
              role="listitem"
              className="flex items-start gap-2 text-xs text-amber-800 dark:text-amber-300"
            >
              <span className="mt-0.5 shrink-0 font-bold">{i + 1}.</span>
              <span>{risk}</span>
            </div>
          ))}
        </div>

        {/* Defense basis dropdown */}
        <div className="space-y-1.5">
          <label
            htmlFor="accept-defense-basis"
            className="block text-sm font-medium"
          >
            RADV defense basis
            <span className="text-destructive ml-1" aria-hidden="true">*</span>
          </label>
          <select
            id="accept-defense-basis"
            value={defenseBasis}
            onChange={(e) => setDefenseBasis(e.target.value)}
            className={cn(
              "w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              "dark:bg-background dark:border-border",
              !basisValid && defenseBasis === "" && "text-muted-foreground"
            )}
            aria-required="true"
            aria-label="Select the RADV defense basis for this override"
          >
            <option value="" disabled>
              {DEFENSE_BASIS_PLACEHOLDER}
            </option>
            {DEFENSE_BASIS_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
        </div>

        {/* Override reason textarea */}
        <div className="space-y-1.5">
          <label
            htmlFor="accept-override-reason"
            className="block text-sm font-medium"
          >
            Why is this still defensible?
            <span className="text-destructive ml-1" aria-hidden="true">*</span>
          </label>
          <textarea
            id="accept-override-reason"
            ref={textareaRef}
            value={overrideReason}
            onChange={(e) => setOverrideReason(e.target.value)}
            placeholder="Describe the clinical basis for accepting despite the risk flags…"
            rows={3}
            className="w-full resize-none rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:bg-background dark:border-border"
            aria-required="true"
            aria-label="Why is this suspect still defensible for RADV"
            aria-describedby="accept-reason-hint"
          />
          <p
            id="accept-reason-hint"
            className={cn(
              "text-xs",
              reasonValid
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-muted-foreground"
            )}
          >
            {reasonValid
              ? "Minimum length met."
              : `${charsLeft} more character${charsLeft === 1 ? "" : "s"} required`}
          </p>
        </div>
      </div>

      <DialogFooter>
        <Button
          variant="outline"
          onClick={onClose}
          aria-label="Cancel and go back"
        >
          Cancel
        </Button>
        <Button
          variant="default"
          onClick={handleSubmit}
          disabled={!canSubmit}
          aria-label="Accept suspect with documented override reason"
          className={cn(
            "bg-amber-600 hover:bg-amber-700 text-white dark:bg-amber-600 dark:hover:bg-amber-700",
            "disabled:opacity-50 disabled:cursor-not-allowed"
          )}
        >
          Accept anyway
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

// ---------------------------------------------------------------------------
// Public export — remounts inner component on each open to reset all state
// ---------------------------------------------------------------------------

export function AcceptConfirmDialog({
  open,
  onClose,
  onConfirm,
  suspect,
}: AcceptConfirmDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) onClose(); }}>
      {open && (
        <AcceptConfirmDialogInner
          suspect={suspect}
          onClose={onClose}
          onConfirm={onConfirm}
        />
      )}
    </Dialog>
  );
}
