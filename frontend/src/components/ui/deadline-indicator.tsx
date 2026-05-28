"use client";

/**
 * DeadlineIndicator — recapture-gap year-end deadline urgency component.
 *
 * Usage examples:
 *   // Table cell (single line)
 *   <DeadlineIndicator daysRemaining={42} size="sm" />
 *
 *   // Card (two lines, with label)
 *   <DeadlineIndicator daysRemaining={12} size="md" showLabel />
 *
 *   // Compact urgency pill (e.g. in a badge column)
 *   <UrgencyBadge daysRemaining={5} />
 *   <UrgencyBadge daysRemaining={42} />
 *   <UrgencyBadge daysRemaining={-3} />
 */

import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export interface DeadlineIndicatorProps {
  daysRemaining: number;
  size?: "sm" | "md";
  showLabel?: boolean;
  className?: string;
}

// ---------------------------------------------------------------------------
// Urgency tiers
// ---------------------------------------------------------------------------

type UrgencyTier = "safe" | "moderate" | "closing" | "urgent" | "critical" | "expired";

interface TierConfig {
  tier: UrgencyTier;
  /** Short inline label shown for mid/high urgency (null = no label for calm tiers) */
  shortLabel: string | null;
  /** Full label for md size */
  fullLabel: string;
  /** Bar fill color class */
  barColor: string;
  /** Track background */
  trackColor: string;
  /** Text color */
  textColor: string;
  /** Pulse animation on bar */
  pulse: boolean;
  /** Pulse speed: normal animate-pulse vs faster custom */
  pulseFast: boolean;
}

function resolveTier(days: number): TierConfig {
  if (days < 0) {
    return {
      tier: "expired",
      shortLabel: "EXPIRED",
      fullLabel: "Expired",
      barColor: "bg-gray-400 dark:bg-gray-500",
      trackColor: "bg-gray-100 dark:bg-gray-800",
      textColor: "text-gray-500 dark:text-gray-400",
      pulse: false,
      pulseFast: false,
    };
  }
  if (days <= 6) {
    return {
      tier: "critical",
      shortLabel: "CRITICAL",
      fullLabel: "Critical",
      barColor: "bg-red-500 dark:bg-red-500",
      trackColor: "bg-red-100 dark:bg-red-950/50",
      textColor: "text-red-600 dark:text-red-400",
      pulse: true,
      pulseFast: true,
    };
  }
  if (days <= 29) {
    return {
      tier: "urgent",
      shortLabel: "URGENT",
      fullLabel: "Urgent",
      barColor: "bg-orange-500 dark:bg-orange-500",
      trackColor: "bg-orange-100 dark:bg-orange-950/50",
      textColor: "text-orange-600 dark:text-orange-400",
      pulse: true,
      pulseFast: false,
    };
  }
  if (days <= 59) {
    return {
      tier: "closing",
      shortLabel: "Closing Soon",
      fullLabel: "Closing Soon",
      barColor: "bg-amber-400 dark:bg-amber-400",
      trackColor: "bg-amber-50 dark:bg-amber-950/40",
      textColor: "text-amber-600 dark:text-amber-400",
      pulse: false,
      pulseFast: false,
    };
  }
  if (days <= 89) {
    return {
      tier: "moderate",
      shortLabel: null,
      fullLabel: "",
      barColor: "bg-teal-500 dark:bg-teal-400",
      trackColor: "bg-teal-50 dark:bg-teal-950/40",
      textColor: "text-teal-700 dark:text-teal-300",
      pulse: false,
      pulseFast: false,
    };
  }
  // 90+
  return {
    tier: "safe",
    shortLabel: null,
    fullLabel: "",
    barColor: "bg-emerald-500 dark:bg-emerald-400",
    trackColor: "bg-emerald-50 dark:bg-emerald-950/40",
    textColor: "text-emerald-700 dark:text-emerald-300",
    pulse: false,
    pulseFast: false,
  };
}

/**
 * Percent of the year already elapsed (0–100), used to fill the bar from left.
 * When days <= 0 the bar is fully filled (100 %).
 * Cap the total year at 365 days so the fill never exceeds 100 %.
 */
function barFillPercent(daysRemaining: number): number {
  if (daysRemaining <= 0) return 100;
  const totalDays = 365;
  const elapsed = totalDays - Math.min(daysRemaining, totalDays);
  return Math.round((elapsed / totalDays) * 100);
}

// ---------------------------------------------------------------------------
// Sub-component: the progress bar itself
// ---------------------------------------------------------------------------

interface ProgressBarProps {
  fillPercent: number;
  config: TierConfig;
  heightClass: string;
}

function DeadlineProgressBar({ fillPercent, config, heightClass }: ProgressBarProps) {
  return (
    <div
      role="progressbar"
      aria-valuenow={fillPercent}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={`Year elapsed: ${fillPercent}%`}
      className={cn(
        "relative w-full overflow-hidden rounded-full",
        heightClass,
        config.trackColor
      )}
    >
      <div
        className={cn(
          "h-full rounded-full transition-all duration-500",
          config.barColor,
          config.pulse && !config.pulseFast && "animate-pulse",
          config.pulseFast && "animate-[pulse_0.8s_ease-in-out_infinite]"
        )}
        style={{ width: `${fillPercent}%` }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * DeadlineIndicator
 *
 * size="sm"  — single line: colored text + compact bar side-by-side
 * size="md"  — two lines: bar on top, descriptive text below
 */
export function DeadlineIndicator({
  daysRemaining,
  size = "md",
  showLabel = true,
  className,
}: DeadlineIndicatorProps) {
  const config = resolveTier(daysRemaining);
  const fillPct = barFillPercent(daysRemaining);

  // Build the display text
  const isExpired = daysRemaining < 0;

  // sm inline label: "Urgent — 12 days" or "42 days left"
  const smText = (() => {
    if (isExpired) return "Expired";
    if (config.shortLabel && config.tier !== "closing") {
      return `${config.shortLabel} — ${daysRemaining}d`;
    }
    if (config.tier === "closing") {
      return `Closing Soon — ${daysRemaining}d`;
    }
    return `${daysRemaining} days left`;
  })();

  // md descriptive text: "42 days remaining until year-end"
  const mdText = (() => {
    if (isExpired) return "Deadline has passed";
    if (daysRemaining === 0) return "Deadline is today";
    if (daysRemaining === 1) return "1 day remaining until year-end";
    return `${daysRemaining} days remaining until year-end`;
  })();

  // md urgency prefix label (Critical / Urgent / Closing Soon)
  const mdUrgencyLabel = config.shortLabel;

  // ---- sm: single-line layout -----------------------------------------------
  if (size === "sm") {
    return (
      <div
        className={cn("flex items-center gap-2 min-w-0", className)}
        aria-label={smText}
      >
        {/* text */}
        <span
          className={cn(
            "shrink-0 text-xs font-semibold tabular-nums whitespace-nowrap",
            config.textColor,
            config.pulse && !config.pulseFast && "animate-pulse",
            config.pulseFast && "animate-[pulse_0.8s_ease-in-out_infinite]"
          )}
        >
          {smText}
        </span>
        {/* bar */}
        {showLabel && (
          <DeadlineProgressBar
            fillPercent={fillPct}
            config={config}
            heightClass="h-1.5 min-w-[48px] max-w-[80px]"
          />
        )}
      </div>
    );
  }

  // ---- md: two-line layout --------------------------------------------------
  return (
    <div className={cn("flex flex-col gap-1.5 w-full", className)}>
      {/* Row 1: bar */}
      <DeadlineProgressBar
        fillPercent={fillPct}
        config={config}
        heightClass="h-2"
      />
      {/* Row 2: text */}
      {showLabel && (
        <div className="flex items-baseline gap-1.5 flex-wrap">
          {mdUrgencyLabel && (
            <span
              className={cn(
                "text-xs font-bold uppercase tracking-wide shrink-0",
                config.textColor,
                config.pulse && !config.pulseFast && "animate-pulse",
                config.pulseFast && "animate-[pulse_0.8s_ease-in-out_infinite]"
              )}
            >
              {mdUrgencyLabel} —
            </span>
          )}
          <span
            className={cn(
              "text-xs",
              mdUrgencyLabel
                ? cn("font-medium", config.textColor)
                : "text-muted-foreground"
            )}
          >
            {mdText}
          </span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// UrgencyBadge — compact pill for table/list columns
// ---------------------------------------------------------------------------

/**
 * UrgencyBadge
 *
 * Returns a colored pill with a short count.
 * Examples:
 *   daysRemaining=120  → "120d"          (emerald)
 *   daysRemaining=42   → "42d"           (teal)
 *   daysRemaining=25   → "Closing 25d"   (amber)
 *   daysRemaining=10   → "URGENT 10d"    (orange, pulsing)
 *   daysRemaining=3    → "CRITICAL 3d"   (red, fast pulsing)
 *   daysRemaining=-1   → "EXPIRED"       (gray)
 */
export function UrgencyBadge({ daysRemaining }: { daysRemaining: number }) {
  const config = resolveTier(daysRemaining);

  // Background map per tier
  const bgMap: Record<UrgencyTier, string> = {
    safe:     "bg-emerald-50  dark:bg-emerald-950/50  ring-emerald-200  dark:ring-emerald-800/60",
    moderate: "bg-teal-50     dark:bg-teal-950/50     ring-teal-200     dark:ring-teal-800/60",
    closing:  "bg-amber-50    dark:bg-amber-950/50    ring-amber-200    dark:ring-amber-800/60",
    urgent:   "bg-orange-50   dark:bg-orange-950/50   ring-orange-200   dark:ring-orange-800/60",
    critical: "bg-red-50      dark:bg-red-950/50      ring-red-200      dark:ring-red-800/60",
    expired:  "bg-gray-100    dark:bg-gray-800/60     ring-gray-200     dark:ring-gray-700",
  };

  const label = (() => {
    if (daysRemaining < 0) return "EXPIRED";
    if (config.tier === "critical") return `CRITICAL ${daysRemaining}d`;
    if (config.tier === "urgent")   return `URGENT ${daysRemaining}d`;
    if (config.tier === "closing")  return `Closing ${daysRemaining}d`;
    return `${daysRemaining}d`;
  })();

  return (
    <span
      role="status"
      aria-label={`${daysRemaining < 0 ? "Deadline expired" : `${daysRemaining} days remaining`}`}
      className={cn(
        "inline-flex items-center justify-center rounded-md px-1.5 py-0.5",
        "text-xs font-semibold tracking-tight whitespace-nowrap",
        "ring-1 ring-inset",
        bgMap[config.tier],
        config.textColor,
        config.pulse && !config.pulseFast && "animate-pulse",
        config.pulseFast && "animate-[pulse_0.8s_ease-in-out_infinite]"
      )}
    >
      {label}
    </span>
  );
}
