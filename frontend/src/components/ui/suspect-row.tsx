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
import { humanizeEvidence } from "@/lib/evidence-labels";
import {
  Loader2,
  Check,
  XCircle,
  HelpCircle,
  MoreHorizontal,
  MessageSquareWarning,
  AlertTriangle,
  ThumbsUp,
  ThumbsDown,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
} from "@/components/ui/dropdown-menu";

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
  /**
   * Backend meat_status string: "complete" | "partial" | "missing" | "unknown"
   * Drives the MEAT status badge colour. Independent of the M/E/A/T letter chips.
   */
  meatStatus?: string | null;
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
  /** Called when "Request documentation" is chosen from the More menu. */
  onRequestDocs?: () => void;
  /** Called when "Force accept (RADV risk)" is chosen. Only rendered when isMeatMissing. */
  onForceAccept?: () => void;
  /** Called when thumbs-up feedback is chosen from the More menu. */
  onFeedbackHelpful?: () => void;
  /** Called when thumbs-down feedback is chosen from the More menu. */
  onFeedbackIncorrect?: () => void;
  /** When true the feedback items are disabled (already submitted). */
  feedbackSent?: boolean;
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

/**
 * MeatStatusBadge — coloured badge for the backend meat_status string.
 *
 * Color semantics:
 *   complete → green   (good — all MEAT criteria met)
 *   partial  → amber   (review needed before accepting)
 *   missing  → red     (no documentation found)
 *   unknown  → neutral gray with "?" prefix (not determined yet)
 *   null/undefined → same as unknown
 */
function MeatStatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) {
    return (
      <span
        title="MEAT status has not been determined yet"
        className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-semibold border border-zinc-200 bg-zinc-100 text-zinc-500 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-400 cursor-default select-none"
      >
        ? unknown
      </span>
    );
  }

  const s = status.toLowerCase();

  if (s === "complete") {
    return (
      <span
        title="MEAT documentation is complete"
        className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold border border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300 cursor-default select-none"
      >
        complete
      </span>
    );
  }

  if (s === "partial") {
    return (
      <span
        title="Some MEAT criteria are documented; review before accepting"
        className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold border border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-300 cursor-default select-none"
      >
        partial
      </span>
    );
  }

  if (s === "missing") {
    return (
      <span
        title="No MEAT documentation found — force-accept required to proceed"
        className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-semibold border border-red-300 bg-red-50 text-red-700 dark:border-red-700 dark:bg-red-950/40 dark:text-red-300 cursor-default select-none"
      >
        <AlertTriangle className="h-2.5 w-2.5" aria-hidden />
        missing
      </span>
    );
  }

  // "unknown" or any unrecognised value → neutral gray
  return (
    <span
      title={`MEAT status: ${status}`}
      className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-semibold border border-zinc-200 bg-zinc-100 text-zinc-500 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-400 cursor-default select-none"
    >
      ? {s}
    </span>
  );
}

function MeatBadges({
  meat,
  meatEvidence,
}: {
  meat?: SuspectMeatValues | null;
  meatEvidence?: SuspectMeatEvidence | null;
}) {
  if (meat == null) return null;

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
              "inline-flex h-5 w-5 items-center justify-center rounded text-[10px] font-bold border cursor-help select-none transition-colors",
              present
                ? cn(def.presentBg, def.presentText, def.presentBorder)
                : "bg-muted/50 text-muted-foreground/40 border-muted",
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
// Confidence pill — compact coloured pill, replaces the old bar+badge pair
// ---------------------------------------------------------------------------

function ConfidencePill({ pct }: { pct: number }) {
  const tier = confidenceTier(pct);

  const pillCls =
    tier.color === "emerald"
      ? "bg-emerald-50 border-emerald-200 text-emerald-700 dark:bg-emerald-950/50 dark:border-emerald-800 dark:text-emerald-400"
      : tier.color === "amber"
      ? "bg-amber-50 border-amber-200 text-amber-700 dark:bg-amber-950/50 dark:border-amber-800 dark:text-amber-400"
      : "bg-red-50 border-red-200 text-red-700 dark:bg-red-950/50 dark:border-red-800 dark:text-red-400";

  return (
    <span
      className={cn(
        "inline-flex items-center justify-center rounded-full border px-2 py-0.5",
        "text-[11px] font-bold tabular-nums shrink-0 w-[46px]",
        pillCls,
      )}
      title={`${tier.label}: ${pct}%`}
      aria-label={`${tier.label}: ${pct}%`}
      role="img"
    >
      {pct}%
    </span>
  );
}

// ---------------------------------------------------------------------------
// Revenue amount
// ---------------------------------------------------------------------------

function RevenueAmount({ dollars }: { dollars: number | null | undefined }) {
  if (dollars == null || dollars === 0) {
    return (
      <span className="text-xs text-muted-foreground tabular-nums">—</span>
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
    <span
      className="inline-flex items-baseline gap-0.5"
      aria-label={`Revenue impact: $${Math.round(abs).toLocaleString("en-US")} per year`}
    >
      <span className="text-sm font-bold tabular-nums text-teal-700 dark:text-teal-400 leading-tight">
        {formatted}
      </span>
      <span className="text-[10px] text-muted-foreground font-medium">/yr</span>
    </span>
  );
}

// ---------------------------------------------------------------------------
// Evidence source badge
// ---------------------------------------------------------------------------

function SourceBadge({ source }: { source: string | null | undefined }) {
  if (!source) return null;

  const label = humanizeEvidence(source);

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
  meatStatus,
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
  onRequestDocs,
  onForceAccept,
  onFeedbackHelpful,
  onFeedbackIncorrect,
  feedbackSent = false,
  className,
}: SuspectRowProps) {
  const confPct = Math.round((confidence ?? 0) * 100);

  return (
    <div
      className={cn(
        // Base: compact card, minimal padding
        "group flex flex-col gap-2 rounded-lg border border-border bg-card px-3 py-2.5",
        "transition-colors hover:bg-muted/20 dark:hover:bg-muted/10",
        // Desktop: single horizontal row constrained to ~64px tall
        "md:flex-row md:items-center md:gap-3 md:py-0 md:min-h-[60px] md:max-h-[72px]",
        className,
      )}
    >
      {/* ── 1. Confidence pill ───────────────────────────────────────── */}
      <ConfidencePill pct={confPct} />

      {/* ── 2. Identity: HCC · ICD-10 · Condition name · badges ─────── */}
      <div className="flex min-w-0 flex-1 flex-col gap-0.5 justify-center">
        {/* Chip row */}
        <div className="flex flex-wrap items-center gap-1.5">
          {/* HCC code */}
          <span className="inline-flex items-center rounded bg-sky-50 dark:bg-sky-950/50 border border-sky-200 dark:border-sky-800 px-1.5 py-0.5 text-[11px] font-bold font-mono text-sky-700 dark:text-sky-400 shrink-0">
            HCC {hcc}
          </span>
          {/* ICD-10 */}
          <span className="inline-flex items-center rounded bg-muted border border-border px-1.5 py-0.5 text-[11px] font-mono font-semibold text-muted-foreground shrink-0">
            {icd10}
          </span>
          {/* Taxonomy badge — tiny, de-emphasised */}
          {taxonomyBadge && (
            <span
              title={taxonomyBadge.title}
              className={cn(
                "inline-flex items-center rounded border px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-widest shrink-0",
                taxonomyBadge.className,
              )}
            >
              {taxonomyBadge.label}
            </span>
          )}
          {/* Evidence source */}
          <SourceBadge source={evidenceSource} />
          {/* Trumped — inline with chips */}
          {isTrumped && trumpedByHcc != null && (
            <span
              className="inline-flex items-center gap-0.5 rounded border border-amber-300 bg-amber-50 dark:border-amber-700 dark:bg-amber-950/40 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-amber-800 dark:text-amber-300"
              title={`CMS-HCC V28 will trump this code. HCC ${trumpedByHcc} already covers this hierarchy.`}
            >
              Trumped by HCC {trumpedByHcc}
            </span>
          )}
        </div>
        {/* Condition name — single line on desktop */}
        <span className="text-sm font-semibold leading-snug text-foreground truncate">
          {label}
        </span>
      </div>

      {/* ── 3. MEAT: letter chips + status badge ────────────────────── */}
      <div className="flex items-center gap-1.5 shrink-0">
        <MeatBadges meat={meat} meatEvidence={meatEvidence} />
        <MeatStatusBadge status={meatStatus} />
      </div>

      {/* ── 4. Revenue ──────────────────────────────────────────────── */}
      <div className="shrink-0 min-w-[52px] flex justify-end">
        <RevenueAmount dollars={revenueDollars} />
      </div>

      {/* ── 5. Actions: Accept · Dismiss · overflow menu ────────────── */}
      <div className="flex items-center gap-1 shrink-0">
        {/* Accept — teal solid when enabled */}
        <Button
          size="sm"
          onClick={onAccept}
          disabled={busy !== null || isTrumped || isMeatMissing}
          title={
            isTrumped
              ? `Accept disabled — HCC ${trumpedByHcc} already covers this hierarchy in V28.`
              : isMeatMissing
              ? "Add MEAT evidence before accepting. Use ••• → Force accept if needed."
              : "Accept this suspect condition (A)"
          }
          aria-disabled={busy !== null || isTrumped || isMeatMissing}
          className={cn(
            "h-7 px-2.5 text-xs font-semibold",
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

        {/* Dismiss — outline */}
        <Button
          size="sm"
          variant="outline"
          onClick={onDismiss}
          disabled={busy !== null}
          className="h-7 px-2.5 text-xs font-semibold text-muted-foreground hover:text-foreground"
          title="Dismiss this suspect (D)"
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

        {/* Overflow menu — Why?, Request docs, Force accept, Feedback */}
        <DropdownMenu>
          <DropdownMenuTrigger
            disabled={busy !== null}
            aria-label="More actions"
            className={cn(
              "inline-flex h-7 w-7 items-center justify-center rounded-md border border-border bg-background",
              "text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
              "disabled:pointer-events-none disabled:opacity-50",
            )}
          >
            <MoreHorizontal className="h-3.5 w-3.5" aria-hidden />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" side="bottom">
            {onWhy && (
              <DropdownMenuItem onClick={onWhy}>
                <HelpCircle className="text-muted-foreground" aria-hidden />
                Why was this flagged?
                <DropdownMenuShortcut>R</DropdownMenuShortcut>
              </DropdownMenuItem>
            )}

            {onRequestDocs && (
              <DropdownMenuItem onClick={onRequestDocs}>
                <MessageSquareWarning className="text-muted-foreground" aria-hidden />
                Request documentation
              </DropdownMenuItem>
            )}

            {isMeatMissing && onForceAccept && (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={onForceAccept}
                  className="text-amber-700 dark:text-amber-400 focus:text-amber-800 dark:focus:text-amber-300 focus:bg-amber-50 dark:focus:bg-amber-950/30"
                >
                  <AlertTriangle className="text-amber-600 dark:text-amber-500" aria-hidden />
                  Force accept (RADV risk)
                </DropdownMenuItem>
              </>
            )}

            {(onFeedbackHelpful || onFeedbackIncorrect) && (
              <>
                <DropdownMenuSeparator />
                {onFeedbackHelpful && (
                  <DropdownMenuItem onClick={onFeedbackHelpful} disabled={feedbackSent}>
                    <ThumbsUp className="text-muted-foreground" aria-hidden />
                    Suggestion was helpful
                  </DropdownMenuItem>
                )}
                {onFeedbackIncorrect && (
                  <DropdownMenuItem onClick={onFeedbackIncorrect} disabled={feedbackSent}>
                    <ThumbsDown className="text-muted-foreground" aria-hidden />
                    Suggestion is incorrect
                  </DropdownMenuItem>
                )}
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}

export default SuspectRow;
