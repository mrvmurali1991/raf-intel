"use client";

/**
 * Term — glossary-powered inline tooltip for healthcare terminology.
 *
 * Usage:
 *   <Term>RAF</Term>
 *   <Term term="RAF Score">RAF Score</Term>
 *   <Term>HCC</Term>
 *
 * If the term (or the `term` override) is not in GLOSSARY, children are
 * rendered as plain text with no tooltip or underline.
 *
 * The GLOSSARY is also exported so other components can look up definitions
 * directly (e.g. for help panels, search, etc.).
 */

import React from "react";
import {
  TooltipProvider,
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Glossary
// ---------------------------------------------------------------------------

export const GLOSSARY: Record<string, string> = {
  RAF: "Risk Adjustment Factor — a score CMS assigns to each Medicare patient. Higher RAF = sicker patient = higher payment to the health plan.",
  "RAF Score":
    "Risk Adjustment Factor score — the numeric value (e.g., 1.234) that determines CMS payment. Built from demographic factors + HCC codes.",
  HCC: "Hierarchical Condition Category — a grouping of ICD-10 diagnosis codes. Each active HCC adds to the patient's RAF score and revenue.",
  MEAT: "Monitor, Evaluate, Assess, Treat — the four CMS criteria that must be documented for an HCC to be valid for risk adjustment.",
  V24: "CMS-HCC Model Version 24 — the older risk adjustment model being phased out by CMS.",
  V28: "CMS-HCC Model Version 28 — the current CMS risk adjustment model (100% weight from 2026+).",
  Suspect:
    "An HCC that AI identified as likely present based on clinical evidence, but not yet documented in this year's claims.",
  Recapture:
    "Re-documenting a chronic HCC from last year in this year's encounters. Without recapture, the HCC drops off and revenue is lost.",
  Attestation:
    "A provider's formal confirmation that a suspected condition is clinically valid and properly documented.",
  HEDIS:
    "Healthcare Effectiveness Data and Information Set — quality measures used by NCQA to rate health plan performance.",
  STARS:
    "CMS Star Ratings — 1-to-5-star quality rating for Medicare Advantage plans. Higher stars = higher bonus payments.",
  "ICD-10":
    "International Classification of Diseases, 10th revision — the standard code set for documenting diagnoses (e.g., E11.9 = Type 2 Diabetes).",
  NPI: "National Provider Identifier — a unique 10-digit number for each healthcare provider.",
  "Recapture Gap":
    "A chronic HCC captured last year that hasn't been re-documented this year — if missed, that revenue is permanently lost.",
  "Revenue at Risk":
    "The dollar amount the health plan will lose if open HCC gaps and suspects are not captured before the submission deadline.",
  "Dual Status":
    "A patient enrolled in both Medicare and Medicaid — dual-eligible patients have different RAF coefficient tables.",
  OREC: "Original Reason for Entitlement Code — indicates why a patient first qualified for Medicare (age, disability, ESRD).",
  "Model Segment":
    "The demographic category used for RAF calculation (e.g., CNA = Community Non-Dual Aged, CFA = Community Full-Dual Aged).",
  "Normalization Factor":
    "CMS adjustment applied to RAF scores to account for coding intensity trends across the industry.",
  FHIR: "Fast Healthcare Interoperability Resources — a modern API standard for exchanging electronic health records.",
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface TermProps {
  /** Visible label. Typically the term itself, but can be any inline content. */
  children: React.ReactNode;
  /**
   * Explicit glossary lookup key. Use when the display text differs from the
   * canonical key, e.g. <Term term="RAF Score">RAF</Term>.
   * Defaults to the string value of `children`.
   */
  term?: string;
  /** Extra classes forwarded to the trigger span. */
  className?: string;
}

export function Term({ children, term, className }: TermProps) {
  // Resolve the lookup key: prefer explicit `term`, fall back to children as string.
  const key =
    term ??
    (typeof children === "string" ? children : undefined);

  const definition = key ? GLOSSARY[key] : undefined;

  // No definition found — render plain children so callers can safely wrap any
  // text without worrying about missing entries.
  if (!definition) {
    return <>{children}</>;
  }

  return (
    <TooltipProvider delay={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          {/*
           * The trigger is an inline span styled to signal interactivity:
           *   - dotted underline in muted colour
           *   - help cursor
           *   - focusable for keyboard / screen-reader users
           * The ⓘ icon sits at text-baseline so it never disturbs line-height.
           */}
          <span
            tabIndex={0}
            role="button"
            aria-label={`Definition: ${key}`}
            className={cn(
              "inline-flex cursor-help items-baseline gap-0.5 outline-none",
              "border-b border-dotted border-muted-foreground/40",
              "focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:rounded-sm",
              className
            )}
          >
            {children}
            {/* Info badge — 12 px, muted, tucked close to the term */}
            <span
              aria-hidden
              className="inline-block text-[10px] leading-none text-muted-foreground/50 translate-y-[-1px] select-none"
            >
              ⓘ
            </span>
          </span>
        </TooltipTrigger>

        {/*
         * Tooltip content: dark background (bg-foreground), white text,
         * max-width 280 px, rounded-lg, shadow-lg.
         * `side="top"` with base-ui's portal handles viewport-edge flipping
         * automatically — the tooltip will appear below when near the top edge.
         */}
        <TooltipContent
          side="top"
          sideOffset={6}
          className={cn(
            "max-w-[280px] rounded-lg px-3 py-2",
            "text-xs leading-relaxed font-normal text-background",
            "shadow-lg"
          )}
        >
          {/* Term name in bold, definition on the next line */}
          <p>
            <span className="font-semibold">{key}</span>
            <br />
            {definition}
          </p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
