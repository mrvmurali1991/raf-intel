"use client";

/**
 * RevenueDisplay — single source of truth for all monetary values in the app.
 *
 * Usage examples:
 *
 *   // Inline in a table cell
 *   <RevenueDisplay value={850} size="xs" />
 *
 *   // KPI card, compact with color
 *   <RevenueDisplay value={3200} size="md" compact colorCode />
 *
 *   // Dashboard hero, animated, with trend arrow
 *   <RevenueDisplay value={1_300_000} size="xl" compact colorCode showTrend animate />
 *
 *   // Labeled block (Revenue at Risk card)
 *   <RevenueDisplay
 *     value={-42_000}
 *     size="lg"
 *     compact
 *     colorCode
 *     showTrend
 *     label="Revenue at Risk"
 *     sublabel="per year"
 *     animate
 *   />
 *
 *   // Full number (no compact shortening)
 *   <RevenueDisplay value={3200} compact={false} />  → "$3,200"
 */

import * as React from "react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface RevenueDisplayProps {
  /** Raw dollar value. Negative values render in red when colorCode=true. */
  value: number;
  /**
   * Visual size of the primary number.
   * xs  → text-xs            (inline table cells)
   * sm  → text-sm            (card sub-values)
   * md  → text-lg font-semibold  (KPI cards)
   * lg  → text-2xl font-bold     (dashboard hero)
   * xl  → text-4xl font-bold     (summary pages)
   */
  size?: "xs" | "sm" | "md" | "lg" | "xl";
  /** Prepend "+" for positive values: "+$3.2K" */
  showSign?: boolean;
  /** Render an inline SVG chevron arrow before the value (↑ green / ↓ red). */
  showTrend?: boolean;
  /**
   * When true (default): abbreviate to $3.2K / $1.3M.
   * When false: full number with commas — "$3,200".
   */
  compact?: boolean;
  /**
   * When true: positive → emerald, negative → red, zero → muted.
   * When false (default): always foreground colour.
   */
  colorCode?: boolean;
  /** Small uppercase label rendered ABOVE the value. */
  label?: string;
  /** Small muted text rendered BELOW the value. */
  sublabel?: string;
  /**
   * Count-up animation from 0 → value over 800 ms with ease-out.
   * Only fires once on first mount.
   */
  animate?: boolean;
  className?: string;
}

// ---------------------------------------------------------------------------
// Size map
// ---------------------------------------------------------------------------

const sizeClasses: Record<NonNullable<RevenueDisplayProps["size"]>, string> = {
  xs: "text-xs",
  sm: "text-sm",
  md: "text-lg font-semibold",
  lg: "text-2xl font-bold",
  xl: "text-4xl font-bold",
};

// Arrow icon sizes to match text
const arrowSizeMap: Record<NonNullable<RevenueDisplayProps["size"]>, number> = {
  xs: 10,
  sm: 11,
  md: 14,
  lg: 18,
  xl: 26,
};

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

/**
 * Format a number compactly:
 *   < 1 000     → "$850"
 *   1K – 999K   → "$3.2K" | "$142K"
 *   ≥ 1M        → "$1.3M" | "$8.7M"
 * Negative sign is stripped here; caller decides prefix.
 */
function formatCompact(abs: number): string {
  if (abs >= 1_000_000) {
    const m = abs / 1_000_000;
    // Show one decimal only when it adds information
    const formatted = m % 1 === 0 ? `${m}` : m.toFixed(1).replace(/\.0$/, "");
    return `$${formatted}M`;
  }
  if (abs >= 1_000) {
    const k = abs / 1_000;
    const formatted = k % 1 === 0 ? `${k}` : k.toFixed(1).replace(/\.0$/, "");
    return `$${formatted}K`;
  }
  return `$${Math.round(abs).toLocaleString("en-US")}`;
}

/** Format full number with commas: "$3,200" */
function formatFull(abs: number): string {
  return `$${Math.round(abs).toLocaleString("en-US")}`;
}

function buildDisplayString(
  value: number,
  compact: boolean,
  showSign: boolean,
): string {
  const abs = Math.abs(value);
  const core = compact ? formatCompact(abs) : formatFull(abs);

  if (value < 0) return `-${core}`;
  if (value > 0 && showSign) return `+${core}`;
  return core;
}

// ---------------------------------------------------------------------------
// Count-up hook
// ---------------------------------------------------------------------------

function useCountUp(target: number, enabled: boolean): number {
  const [display, setDisplay] = React.useState(enabled ? 0 : target);
  const firedRef = React.useRef(false);
  const rafRef = React.useRef<number | null>(null);

  React.useEffect(() => {
    if (!enabled || firedRef.current) return;
    firedRef.current = true;

    const duration = 800; // ms
    const start = performance.now();

    function step(now: number) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      // ease-out cubic: 1 - (1 - t)^3
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(target * eased);
      if (progress < 1) {
        rafRef.current = requestAnimationFrame(step);
      } else {
        setDisplay(target);
      }
    }

    rafRef.current = requestAnimationFrame(step);
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, [target, enabled]);

  return display;
}

// ---------------------------------------------------------------------------
// Trend arrow (inline SVG — no emoji, no external icon lib)
// ---------------------------------------------------------------------------

interface TrendArrowProps {
  direction: "up" | "down";
  size: number;
  className?: string;
}

function TrendArrow({ direction, size, className }: TrendArrowProps) {
  // Chevron pointing up or down, stroked.
  const pts =
    direction === "up"
      ? `4,${size - 4} ${size / 2},4 ${size - 4},${size - 4}`
      : `4,4 ${size / 2},${size - 4} ${size - 4},4`;

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      <polyline points={pts} />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// RevenueDisplay
// ---------------------------------------------------------------------------

export function RevenueDisplay({
  value,
  size = "md",
  showSign = false,
  showTrend = false,
  compact = true,
  colorCode = false,
  label,
  sublabel,
  animate = false,
  className,
}: RevenueDisplayProps) {
  const animatedValue = useCountUp(value, animate);
  const displayValue = animate ? animatedValue : value;

  // Colour class for the value
  const colorClass = colorCode
    ? value > 0
      ? "text-emerald-600 dark:text-emerald-400"
      : value < 0
      ? "text-red-600 dark:text-red-400"
      : "text-muted-foreground"
    : "";

  // Trend arrow direction and visibility
  const showArrow = showTrend && value !== 0;
  const arrowDirection = value >= 0 ? "up" : "down";
  const arrowColor =
    value > 0
      ? "text-emerald-600 dark:text-emerald-400"
      : "text-red-600 dark:text-red-400";
  const arrowPx = arrowSizeMap[size];

  const formatted = buildDisplayString(displayValue, compact, showSign);

  const hasLabel = Boolean(label);
  const hasSublabel = Boolean(sublabel);
  const isBlock = hasLabel || hasSublabel;

  if (isBlock) {
    return (
      <div className={cn("flex flex-col gap-0.5", className)}>
        {hasLabel && (
          <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground leading-none">
            {label}
          </span>
        )}

        <div
          className={cn(
            "inline-flex items-center gap-1 tabular-nums leading-none",
            sizeClasses[size],
            colorClass,
          )}
          aria-label={`${label ? label + ": " : ""}${formatted}`}
        >
          {showArrow && (
            <TrendArrow
              direction={arrowDirection}
              size={arrowPx}
              className={arrowColor}
            />
          )}
          <span>{formatted}</span>
        </div>

        {hasSublabel && (
          <span className="text-xs text-muted-foreground leading-none">
            {sublabel}
          </span>
        )}
      </div>
    );
  }

  // Inline (no label/sublabel wrapper)
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 tabular-nums leading-none",
        sizeClasses[size],
        colorClass,
        className,
      )}
      aria-label={formatted}
    >
      {showArrow && (
        <TrendArrow
          direction={arrowDirection}
          size={arrowPx}
          className={arrowColor}
        />
      )}
      <span>{formatted}</span>
    </span>
  );
}

export default RevenueDisplay;
