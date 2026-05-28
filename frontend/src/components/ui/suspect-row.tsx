"use client";

/**
 * SuspectRow — horizontal, information-dense layout for a single RAF suspect.
 *
 * Layout (desktop):
 *   [HCC Code + Label]  [MEAT: M E A T]  [Confidence bar + %]  [$revenue/yr]  [Actions]
 *
 * The component is a PURE DISPLAY / LAYOUT primitive — it owns no mutations, no
 * dialogs, no toast calls. All actions are surfaced via render-prop callbacks so
 * the caller (SuspectCardView) keeps full ownership of business logic.
 *
 * Usage:
 *   <SuspectRow
 *     hcc={18}
 *     icd10="E11.65"
 *     label="Diabetes with Chronic Complications"
 *     confidence={0.87}
 *     meat={{ monitor: true, evaluate: true, assess: true, treat: false }}
 *     meatEvidence={{ monitor: "eGFR trended Q6M", evaluate: "A1c 8.2% ordered", assess: "Noted in SOAP", treat: null }}
 *     revenueDollars={3200}
 *     evidenceSource="Claims"
 *     taxonomyBadge={{ label: "Net-new", className: "..." }}
 *     isTrumped={false}
 *     trumpedByHcc={null}
 *     isMeatMissing={false}
 *     busy={null}
 *     onAccept={() => ...}
 *     onDismiss={() => ...}
 *     onWhy={() => ...}
 *   />
 */

import * as React from "react";
import { cn } from "@/lib/utils";
import { confidenceTier } from "@/lib/confidence";
import { Loader2, Check, XCircle, HelpCircle } from "lucide-react";
import { Button } from "@/components/ui/button";

// ---------------------------------------------------------------------------
// Sub-types
// ---------------------------------------------------------------------------

export interface SuspectMeatValues {
  monitor: boolean;
  evaluate: boolean;
  assess: boolean;
  treat: boolean;
}

/** Per-letter text evidence shown on hover. Any field may be null/undefined. */
export interface SuspectMeatEvidence {
  monitor?: string | null;
  evaluate?: string | null;
  assess?: string | null;
  treat?: string | null;
}

export interface SuspectTaxonomyBadge {
  label: string;
  /** Full Tailwind className string for border/bg/text colours. */
  className: string;
  title?: string;
}

export type SuspectBusy = "accept" | "dismiss" | null;

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface SuspectRowProps {
  hcc: number | string;
  icd10: string;
  label: string;
  /** 0-1 float */
  confidence: number;
  meat?: SuspectMeatValues | null;
  meatEvidence?: SuspectMeatEvidence | null;
  /** Expected annual revenue uplift in whole dollars. Null = unknown. */
  revenueDollars?: number | null;
  /** Short display name for the evidence source: "Claims", "Notes", "Labs", etc. */
  evidenceSource?: string | null;
  taxonomyBadge?: SuspectTaxonomyBadge | null;
  /** When true, Accept is blocked and a "Trumped" overlay is shown. */
  isTrumped?: boolean;
  trumpedByHcc?: number | null;
  /** Accept is blocked until force-accept flow is triggered. */
  isMeatMissing?: boolean;
  busy: SuspectBusy;
  /** Called when the Accept button is clicked (passes gate check). */
  onAccept: () => void;
  /** Called when the Dismiss button is clicked. */
  onDismiss: () => void;
  /** Called when the "Why?" link is clicked. */
  onWhy?: () => void;
  className?: string;
}

// ---------------------------------------------------------------------------
// MEAT badges
// ---------------------------------------------------------------------------

const MEAT_DEFS: {
  key: keyof SuspectMeatValues;
  letter: string;
  full: string;
  presentBg: string;
  presentText: string;
  presentBorder: string;
}[] = [
  {
    key: "monitor",
    letter: "M",
    full: "Monitor",
    presentBg: "bg-teal-100 dark:bg-teal-900/40",
    presentText: "text-teal-800 dark:text-teal-200",
    presentBorder: "border-teal-400 dark:border-teal-600",
  },
  {
    key: "evaluate",
    letter: "E",
    full: "Evaluate",
    presentBg: "bg-purple-100 dark:bg-purple-900/40",
    presentText: "text-purple-800 dark:text-purple-200",
    presentBorder: "border-purple-400 dark:border-purple-600",
  },
  {
    key: "assess",
    letter: "A",
    full: "Assess",
    presentBg: "bg-amber-100 dark:bg-amber-900/40",
    presentText: "text-amber-800 dark:text-amber-200",
    presentBorder: "border-amber-400 dark:border-amber-600",
  },
  {
    key: "treat",
    letter: "T",
    full: "Treat",
    presentBg: "bg-emerald-100 dark:bg-emerald-900/40",
    presentText: "text-emerald-800 dark:text-emerald-200",
    presentBorder: "border-emerald-400 dark:border-emerald-600",
  },
];

function MeatBadges({
  meat,
  meatEvidence,
}: {
  meat?: SuspectMeatValues | null;
  meatEvidence?: SuspectMeatEvidence | null;
}) {
  // When meat is entirely absent, show a single "MEAT unknown" placeholder.
  if (meat == null) {
    return (
      <span
        title="MEAT evidence not yet generated"
        className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-semibold border border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-300 cursor-default select-none"
      >
        MEAT pending
      </span>
    );
  }

  const presentCount = MEAT_DEFS.filter((d) => meat[d.key]).length;

  return (
    <div
      className="flex items-center gap-0.5"
      role="group"
      aria-label={`MEAT criteria: ${presentCount} of 4 met`}
    >
      {MEAT_DEFS.map((def) => {
        const present = !!meat[def.key];
        const evidenceText = meatEvidence?.[def.key];

        // Build tooltip — show evidence text when available.
        const tipPresent = evidenceText
          ? `${def.full}: ${evidenceText}`
          : `${def.full}: documented`;
        const tipMissing = `${def.full}: not documented`;

        return (
          <span
            key={def.key}
            title={present ? tipPresent : tipMissing}
            aria-label={present ? tipPresent : tipMissing}
            className={cn(
              "inline-flex h-6 w-6 items-center justify-center rounded text-[11px] font-bold border cursor-help select-none transition-colors",
              present
                ? cn(def.presentBg, def.presentText, def.presentBorder)
                : "bg-muted/50 text-muted-foreground/50 border-muted",
            )}
          >
            {def.letter}
          </span>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Confidence bar + badge
// ---------------------------------------------------------------------------

function ConfidenceBar({ pct }: { pct: number }) {
  const tier = confidenceTier(pct);

  const barColor =
    tier.color === "emerald"
      ? "bg-emerald-500"
      : tier.color === "amber"
      ? "bg-amber-500"
      : "bg-red-500";

  const textColor =
    tier.color === "emerald"
      ? "text-emerald-700 dark:text-emerald-400"
      : tier.color === "amber"
      ? "text-amber-700 dark:text-amber-400"
      : "text-red-700 dark:text-red-400";

  const badgeBg =
    tier.color === "emerald"
      ? "bg-emerald-50 dark:bg-emerald-950/50 border-emerald-200 dark:border-emerald-800"
      : tier.color === "amber"
      ? "bg-amber-50 dark:bg-amber-950/50 border-amber-200 dark:border-amber-800"
      : "bg-red-50 dark:bg-red-950/50 border-red-200 dark:border-red-800";

  return (
    <div
      className="flex flex-col items-center gap-1 min-w-[56px]"
      title={tier.label}
      aria-label={`${tier.label}: ${pct}%`}
    >
      {/* Percentage badge */}
      <span
        className={cn(
          "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-bold tabular-nums",
          textColor,
          badgeBg,
        )}
      >
        {pct}%
      </span>
      {/* Bar */}
      <div
        className="h-1.5 w-full rounded-full bg-muted overflow-hidden"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className={cn("h-full rounded-full transition-all duration-700 ease-out", barColor)}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Revenue amount
// ---------------------------------------------------------------------------

function RevenueAmount({ dollars }: { dollars: number | null | undefined }) {
  if (dollars == null || dollars === 0) {
    return (
      <span className="text-xs text-muted-foreground tabular-nums">
        —
      </span>
    );
  }

  const abs = Math.abs(dollars);
  let formatted: string;
  if (abs >= 1_000_000) {
    formatted = `$${(abs / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  } else if (abs >= 1_000) {
    formatted = `$${(abs / 1_000).toFixed(1).replace(/\.0$/, "")}K`;
  } else {
    formatted = `$${Math.round(abs).toLocaleString("en-US")}`;
  }

  return (
    <div className="flex flex-col items-end">
      <span
        className="text-base font-bold tabular-nums text-teal-700 dark:text-teal-400 leading-tight"
        aria-label={`Revenue impact: $${Math.round(abs).toLocaleString("en-US")} per year`}
      >
        {formatted}
      </span>
      <span className="text-[10px] text-muted-foreground font-medium leading-tight">/yr</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Evidence source badge
// ---------------------------------------------------------------------------

function SourceBadge({ source }: { source: string | null | undefined }) {
  if (!source) return null;

  // Map common backend evidence_type values to friendlier display labels.
  const label =
    source === "medication"
      ? "Medication"
      : source === "lab"
      ? "Labs"
      : source === "imaging"
      ? "Imaging"
      : source === "referral"
      ? "Referral"
      : source === "historical" || source.startsWith("hist")
      ? "Historical"
      : source === "claim_history" || source.startsWith("claim")
      ? "Claims"
      : source === "note" || source.startsWith("note")
      ? "Notes"
      : source;

  return (
    <span className="inline-flex items-center rounded border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900 px-1.5 py-0.5 text-[10px] font-medium text-zinc-600 dark:text-zinc-400">
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Main SuspectRow
// ---------------------------------------------------------------------------

export function SuspectRow({
  hcc,
  icd10,
  label,
  confidence,
  meat,
  meatEvidence,
  revenueDollars,
  evidenceSource,
  taxonomyBadge,
  isTrumped = false,
  trumpedByHcc,
  isMeatMissing = false,
  busy,
  onAccept,
  onDismiss,
  onWhy,
  className,
}: SuspectRowProps) {
  const confPct = Math.round((confidence ?? 0) * 100);

  return (
    <div
      className={cn(
        // Base card
        "group flex flex-col gap-3 rounded-lg border border-border bg-card px-4 py-3",
        "transition-colors hover:bg-muted/30 dark:hover:bg-muted/10",
        // Desktop: single horizontal row
        "md:flex-row md:items-center md:gap-4",
        className,
      )}
    >
      {/* ── 1. HCC Code + Label ───────────────────────────────────────── */}
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex flex-wrap items-center gap-2">
          {/* HCC code chip */}
          <span className="inline-flex items-center rounded bg-sky-50 dark:bg-sky-950/50 border border-sky-200 dark:border-sky-800 px-1.5 py-0.5 text-[11px] font-bold font-mono text-sky-700 dark:text-sky-400 shrink-0">
            HCC {hcc}
          </span>
          {/* ICD-10 chip */}
          <span className="inline-flex items-center rounded bg-muted border border-border px-1.5 py-0.5 text-[11px] font-mono font-semibold text-muted-foreground shrink-0">
            {icd10}
          </span>
          {/* Taxonomy badge (Net-new / Audit / Confirmed) */}
          {taxonomyBadge && (
            <span
              title={taxonomyBadge.title}
              className={cn(
                "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider shrink-0",
                taxonomyBadge.className,
              )}
            >
              {taxonomyBadge.label}
            </span>
          )}
          {/* Source badge */}
          <SourceBadge source={evidenceSource} />
        </div>

        {/* Condition label — bold, prominent */}
        <span className="text-sm font-semibold leading-snug text-foreground">
          {label}
        </span>

        {/* Trumped notice (inline, below label on mobile) */}
        {isTrumped && trumpedByHcc != null && (
          <span
            className="mt-0.5 inline-flex w-fit items-center gap-1 rounded-full border border-amber-300 bg-amber-50 dark:border-amber-700 dark:bg-amber-950/40 px-2 py-0.5 text-[10px] font-semibold text-amber-800 dark:text-amber-300"
            title={`CMS-HCC V28 will trump this code. HCC ${trumpedByHcc} already covers this hierarchy.`}
          >
            Trumped by HCC {trumpedByHcc}
          </span>
        )}
      </div>

      {/* ── 2. MEAT badges ───────────────────────────────────────────── */}
      <div className="flex items-center gap-2 shrink-0">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground hidden md:block">
          MEAT
        </span>
        <MeatBadges meat={meat} meatEvidence={meatEvidence} />
      </div>

      {/* ── 3. Confidence bar + % ────────────────────────────────────── */}
      <div className="shrink-0 w-16">
        <ConfidenceBar pct={confPct} />
      </div>

      {/* ── 4. Revenue — most important number, right-aligned, teal ──── */}
      <div className="shrink-0 min-w-[64px] text-right">
        <RevenueAmount dollars={revenueDollars} />
      </div>

      {/* ── 5. Action buttons ────────────────────────────────────────── */}
      <div className="flex items-center gap-1.5 shrink-0">
        {/* Accept */}
        <Button
          size="sm"
          onClick={onAccept}
          disabled={busy !== null || isTrumped || isMeatMissing}
          title={
            isTrumped
              ? `Accept disabled — HCC ${trumpedByHcc} already covers this hierarchy in V28.`
              : isMeatMissing
              ? "Add MEAT evidence before accepting."
              : "Accept this suspect condition"
          }
          aria-disabled={busy !== null || isTrumped || isMeatMissing}
          className={cn(
            "h-8 px-3 text-xs font-semibold",
            // Solid teal when enabled
            !isTrumped && !isMeatMissing && busy === null
              ? "bg-teal-600 hover:bg-teal-700 text-white border-transparent dark:bg-teal-700 dark:hover:bg-teal-600"
              : "",
          )}
        >
          {busy === "accept" ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <>
              <Check className="h-3 w-3 mr-1" aria-hidden />
              Accept
            </>
          )}
        </Button>

        {/* Dismiss */}
        <Button
          size="sm"
          variant="outline"
          onClick={onDismiss}
          disabled={busy !== null}
          className="h-8 px-3 text-xs font-semibold text-muted-foreground hover:text-foreground"
          title="Dismiss this suspect"
        >
          {busy === "dismiss" ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <>
              <XCircle className="h-3 w-3 mr-1" aria-hidden />
              Dismiss
            </>
          )}
        </Button>

        {/* Why? */}
        {onWhy && (
          <Button
            size="sm"
            variant="ghost"
            onClick={onWhy}
            disabled={busy !== null}
            aria-label="Why was this flagged?"
            className="h-8 w-8 p-0 text-muted-foreground hover:text-foreground"
            title="Explain why this was flagged"
          >
            <HelpCircle className="h-3.5 w-3.5" aria-hidden />
          </Button>
        )}
      </div>
    </div>
  );
}

export default SuspectRow;
