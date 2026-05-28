"use client";

/**
 * RafScoreBadge — visual RAF score indicator with semi-circular SVG gauge,
 * risk tier color coding, V24/V28 blend detail, and period delta display.
 *
 * RAF score ranges:
 *   0.0 – 0.5  : Low risk       → emerald
 *   0.5 – 1.0  : Below average  → teal
 *   1.0 – 1.5  : Average        → blue
 *   1.5 – 2.5  : Above average  → amber
 *   2.5+       : High risk      → red
 *
 * Usage examples:
 *
 *   // Compact inline badge for table cells
 *   <RafScoreBadge score={1.234} compact />
 *
 *   // Medium gauge card for patient detail header
 *   <RafScoreBadge score={1.234} size="md" showLabel showRisk />
 *
 *   // Full card with blend breakdown and period delta
 *   <RafScoreBadge
 *     score={1.82}
 *     size="lg"
 *     showLabel
 *     showRisk
 *     showBlend
 *     v24Score={0.45}
 *     v28Score={1.82}
 *     previousScore={1.70}
 *   />
 */

import * as React from "react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface RafScoreBadgeProps {
  score: number;
  size?: "sm" | "md" | "lg";
  /** Render "RAF Score" label above the gauge */
  showLabel?: boolean;
  /** Render risk tier label below the score (e.g. "High Risk") */
  showRisk?: boolean;
  /** Render "V24: 0.45 → V28: 1.82" blend detail row */
  showBlend?: boolean;
  v24Score?: number;
  v28Score?: number;
  /** When provided, renders a delta chip vs the previous period */
  previousScore?: number;
  /** Inline pill badge — no gauge. Use inside table cells. */
  compact?: boolean;
  className?: string;
}

// ---------------------------------------------------------------------------
// Risk tier helpers
// ---------------------------------------------------------------------------

type RiskTier = "low" | "below-avg" | "average" | "above-avg" | "high";

interface TierMeta {
  tier: RiskTier;
  label: string;
  /** Tailwind text color class */
  textColor: string;
  /** Tailwind bg class (light tint) */
  bgColor: string;
  /** Tailwind border class */
  borderColor: string;
  /** Hex used for SVG elements that can't take Tailwind classes */
  hex: string;
  /** Hex for a slightly darker stroke on the arc needle */
  hexDark: string;
}

function getTier(score: number): TierMeta {
  if (score < 0.5) {
    return {
      tier: "low",
      label: "Low Risk",
      textColor: "text-emerald-700 dark:text-emerald-400",
      bgColor: "bg-emerald-50 dark:bg-emerald-950/60",
      borderColor: "border-emerald-300 dark:border-emerald-700",
      hex: "#10b981",
      hexDark: "#059669",
    };
  }
  if (score < 1.0) {
    return {
      tier: "below-avg",
      label: "Below Average",
      textColor: "text-teal-700 dark:text-teal-400",
      bgColor: "bg-teal-50 dark:bg-teal-950/60",
      borderColor: "border-teal-300 dark:border-teal-700",
      hex: "#14b8a6",
      hexDark: "#0d9488",
    };
  }
  if (score < 1.5) {
    return {
      tier: "average",
      label: "Average",
      textColor: "text-blue-700 dark:text-blue-400",
      bgColor: "bg-blue-50 dark:bg-blue-950/60",
      borderColor: "border-blue-300 dark:border-blue-700",
      hex: "#3b82f6",
      hexDark: "#2563eb",
    };
  }
  if (score < 2.5) {
    return {
      tier: "above-avg",
      label: "Above Average",
      textColor: "text-amber-700 dark:text-amber-400",
      bgColor: "bg-amber-50 dark:bg-amber-950/60",
      borderColor: "border-amber-300 dark:border-amber-700",
      hex: "#f59e0b",
      hexDark: "#d97706",
    };
  }
  return {
    tier: "high",
    label: "High Risk",
    textColor: "text-red-700 dark:text-red-400",
    bgColor: "bg-red-50 dark:bg-red-950/60",
    borderColor: "border-red-300 dark:border-red-700",
    hex: "#ef4444",
    hexDark: "#dc2626",
  };
}

// ---------------------------------------------------------------------------
// SVG gauge arc
// ---------------------------------------------------------------------------

/**
 * Converts polar (center, radius, angleDeg) to Cartesian (x, y).
 * Angle 0 = 3 o'clock (right), going clockwise.
 */
function polarToCartesian(
  cx: number,
  cy: number,
  r: number,
  angleDeg: number,
): [number, number] {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
}

/**
 * Builds an SVG arc path string from startAngle to endAngle (degrees, 0=top).
 */
function arcPath(
  cx: number,
  cy: number,
  r: number,
  startAngle: number,
  endAngle: number,
): string {
  const [sx, sy] = polarToCartesian(cx, cy, r, startAngle);
  const [ex, ey] = polarToCartesian(cx, cy, r, endAngle);
  const largeArc = endAngle - startAngle > 180 ? 1 : 0;
  return `M ${sx} ${sy} A ${r} ${r} 0 ${largeArc} 1 ${ex} ${ey}`;
}

/**
 * Semi-circular gauge arc spanning -90° (left) to +90° (right), i.e.
 * the bottom half of a circle.  Score 0 maps to the leftmost point and
 * maxScore maps to the rightmost point.
 *
 * The arc background uses a CSS linearGradient: green → teal → blue →
 * amber → red.  The filled portion is a second arc clipped to the current
 * score position, drawn in the tier color.  A small dot marks the position.
 */
interface GaugeArcProps {
  score: number;
  maxScore?: number;
  /** SVG coordinate space width (viewBox units) */
  size?: number;
  tierHex: string;
  tierHexDark: string;
}

function GaugeArc({
  score,
  maxScore = 4,
  size = 100,
  tierHex,
  tierHexDark,
}: GaugeArcProps) {
  const cx = size / 2;
  const cy = size / 2 + size * 0.05; // shift center slightly down so the arc opens toward bottom
  const r = size * 0.38;
  const strokeW = size * 0.07;
  const dotR = size * 0.05;

  // Arc spans from 180° to 360° (clockwise, SVG coords) — the bottom semicircle.
  // In our polarToCartesian convention (0=top, clockwise), this is 180° to 360°.
  const START = 180; // left tip
  const END = 360;   // right tip

  const pct = Math.min(Math.max(score / maxScore, 0), 1);
  const scoreAngle = START + pct * (END - START);

  const bgPath = arcPath(cx, cy, r, START, END);
  const fillPath = arcPath(cx, cy, r, START, scoreAngle);

  const [dotX, dotY] = polarToCartesian(cx, cy, r, scoreAngle);

  // Gradient stop colors for the background track
  const gradId = React.useId().replace(/:/g, "");

  return (
    <svg
      viewBox={`0 0 ${size} ${size}`}
      className="w-full"
      style={{ overflow: "visible" }}
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        {/* Multi-stop gradient spanning the full arc from green → red */}
        <linearGradient id={`raf-grad-${gradId}`} x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%"   stopColor="#10b981" stopOpacity="0.35" />
          <stop offset="25%"  stopColor="#14b8a6" stopOpacity="0.35" />
          <stop offset="50%"  stopColor="#3b82f6" stopOpacity="0.35" />
          <stop offset="75%"  stopColor="#f59e0b" stopOpacity="0.35" />
          <stop offset="100%" stopColor="#ef4444" stopOpacity="0.35" />
        </linearGradient>
        {/* Filled arc gradient in tier color */}
        <linearGradient id={`raf-fill-${gradId}`} x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%"   stopColor={tierHex}     stopOpacity="0.7" />
          <stop offset="100%" stopColor={tierHexDark} stopOpacity="1"   />
        </linearGradient>
      </defs>

      {/* Background arc — full 180° span */}
      <path
        d={bgPath}
        fill="none"
        stroke={`url(#raf-grad-${gradId})`}
        strokeWidth={strokeW}
        strokeLinecap="round"
      />

      {/* Filled arc — up to current score position */}
      {pct > 0.005 && (
        <path
          d={fillPath}
          fill="none"
          stroke={`url(#raf-fill-${gradId})`}
          strokeWidth={strokeW}
          strokeLinecap="round"
        />
      )}

      {/* Marker dot at score position */}
      <circle
        cx={dotX}
        cy={dotY}
        r={dotR}
        fill={tierHexDark}
        stroke="white"
        strokeWidth={size * 0.018}
      />

      {/* Tick marks at 0, 1, 2, 3, 4 */}
      {[0, 1, 2, 3, 4].map((mark) => {
        const tickPct = mark / maxScore;
        const tickAngle = START + tickPct * (END - START);
        const innerR = r - strokeW * 0.55;
        const outerR = r + strokeW * 0.55;
        const [ix, iy] = polarToCartesian(cx, cy, innerR, tickAngle);
        const [ox, oy] = polarToCartesian(cx, cy, outerR, tickAngle);
        // Label position — just beyond the outer edge
        const labelR = outerR + size * 0.07;
        const [lx, ly] = polarToCartesian(cx, cy, labelR, tickAngle);
        return (
          <g key={mark}>
            <line
              x1={ix} y1={iy}
              x2={ox} y2={oy}
              stroke="#94a3b8"
              strokeWidth={size * 0.012}
              strokeLinecap="round"
            />
            <text
              x={lx}
              y={ly}
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize={size * 0.09}
              fill="#94a3b8"
              fontFamily="ui-monospace, monospace"
            >
              {mark}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Delta chip
// ---------------------------------------------------------------------------

function DeltaChip({ current, previous }: { current: number; previous: number }) {
  const delta = current - previous;
  const isUp = delta > 0;
  const isZero = Math.abs(delta) < 0.001;
  const sign = isUp ? "+" : "";
  const arrow = isZero ? "→" : isUp ? "↑" : "↓";
  const colorClass = isZero
    ? "text-slate-500 bg-slate-100 dark:text-slate-400 dark:bg-slate-800"
    : isUp
    ? "text-red-700 bg-red-50 dark:text-red-400 dark:bg-red-950/50"
    : "text-emerald-700 bg-emerald-50 dark:text-emerald-400 dark:bg-emerald-950/50";

  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[10px] font-semibold tabular-nums leading-none",
        colorClass,
      )}
      aria-label={`${isZero ? "Unchanged" : isUp ? "Increased" : "Decreased"} by ${Math.abs(delta).toFixed(3)} vs last period`}
    >
      <span aria-hidden>{arrow}</span>
      {sign}{delta.toFixed(3)}
      <span className="ml-0.5 font-normal opacity-70">vs last</span>
    </span>
  );
}

// ---------------------------------------------------------------------------
// Blend row
// ---------------------------------------------------------------------------

function BlendRow({
  v24,
  v28,
  size,
}: {
  v24: number;
  v28: number;
  size: "sm" | "md" | "lg";
}) {
  const improved = v28 < v24;
  const arrowColor = improved ? "#10b981" : "#ef4444";
  const arrowGlyph = improved ? "↓" : "↑";
  const textSizeClass = size === "sm" ? "text-[9px]" : "text-[10px]";

  return (
    <div
      className={cn(
        "flex items-center justify-center gap-1 tabular-nums text-slate-500 dark:text-slate-400",
        textSizeClass,
      )}
      aria-label={`V24 score ${v24.toFixed(2)}, V28 score ${v28.toFixed(2)}`}
    >
      <span className="font-medium text-slate-600 dark:text-slate-300">V24:</span>
      <span>{v24.toFixed(2)}</span>
      <span aria-hidden style={{ color: arrowColor, fontWeight: 700 }}>{arrowGlyph}</span>
      <span className="font-medium text-slate-600 dark:text-slate-300">V28:</span>
      <span>{v28.toFixed(2)}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Compact inline pill
// ---------------------------------------------------------------------------

function CompactBadge({
  score,
  className,
}: {
  score: number;
  className?: string;
}) {
  const meta = getTier(score);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-xs font-semibold tabular-nums leading-none",
        meta.bgColor,
        meta.borderColor,
        meta.textColor,
        className,
      )}
      aria-label={`RAF score ${score.toFixed(3)}, ${meta.label}`}
      title={`RAF score ${score.toFixed(3)} — ${meta.label}`}
    >
      {/* Color dot */}
      <span
        aria-hidden
        className="inline-block h-1.5 w-1.5 rounded-full shrink-0"
        style={{ background: meta.hex }}
      />
      {score.toFixed(3)}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Card gauge (sm / md / lg)
// ---------------------------------------------------------------------------

const SIZE_CONFIG = {
  sm:  { wClass: "w-20",  textScore: "text-base",   textRisk: "text-[9px]",  textLabel: "text-[9px]",  gaugePad: "px-1 pt-1 pb-0" },
  md:  { wClass: "w-[7.5rem]", textScore: "text-lg", textRisk: "text-[10px]", textLabel: "text-[10px]", gaugePad: "px-2 pt-1.5 pb-0.5" },
  lg:  { wClass: "w-40",  textScore: "text-2xl",    textRisk: "text-xs",     textLabel: "text-[10px]", gaugePad: "px-3 pt-2 pb-1" },
};

function CardGauge({
  score,
  size,
  showLabel,
  showRisk,
  showBlend,
  v24Score,
  v28Score,
  previousScore,
  className,
}: Omit<RafScoreBadgeProps, "compact">) {
  const resolvedSize = size ?? "md";
  const meta = getTier(score);
  const cfg = SIZE_CONFIG[resolvedSize];

  const hasBlend = showBlend && v24Score !== undefined && v28Score !== undefined;
  const hasDelta = previousScore !== undefined;

  return (
    <div
      className={cn(
        "inline-flex flex-col items-center rounded-xl border shadow-sm",
        cfg.wClass,
        cfg.gaugePad,
        meta.bgColor,
        meta.borderColor,
        className,
      )}
      role="img"
      aria-label={`RAF score ${score.toFixed(3)}, ${meta.label}`}
    >
      {/* Optional label above */}
      {showLabel && (
        <span
          className={cn(
            "mb-0.5 font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400",
            cfg.textLabel,
          )}
        >
          RAF Score
        </span>
      )}

      {/* Gauge SVG — takes up the top portion */}
      <div className="relative w-full">
        <GaugeArc
          score={score}
          maxScore={4}
          size={100}
          tierHex={meta.hex}
          tierHexDark={meta.hexDark}
        />

        {/* Score number centered below the arc midpoint */}
        <div
          className="absolute inset-x-0 bottom-[18%] flex flex-col items-center"
          aria-hidden="true"
        >
          <span
            className={cn(
              "font-bold tabular-nums leading-none",
              cfg.textScore,
              meta.textColor,
            )}
          >
            {score.toFixed(3)}
          </span>
        </div>
      </div>

      {/* Risk tier label */}
      {showRisk && (
        <span
          className={cn(
            "mt-0.5 font-semibold leading-none",
            cfg.textRisk,
            meta.textColor,
          )}
        >
          {meta.label}
        </span>
      )}

      {/* V24 / V28 blend row */}
      {hasBlend && (
        <div className="mt-1 w-full">
          <BlendRow v24={v24Score!} v28={v28Score!} size={resolvedSize} />
        </div>
      )}

      {/* Period delta chip */}
      {hasDelta && (
        <div className="mt-1 mb-0.5">
          <DeltaChip current={score} previous={previousScore!} />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Public export
// ---------------------------------------------------------------------------

/**
 * RafScoreBadge — visual RAF score indicator.
 *
 * @example
 *   // In a table cell (compact inline pill)
 *   <RafScoreBadge score={row.raf_score} compact />
 *
 *   // In a patient detail header
 *   <RafScoreBadge score={patient.raf_score} size="md" showLabel showRisk />
 *
 *   // Full detail with V24/V28 split and trend
 *   <RafScoreBadge
 *     score={1.82}
 *     size="lg"
 *     showLabel showRisk showBlend
 *     v24Score={0.45}
 *     v28Score={1.82}
 *     previousScore={1.70}
 *   />
 */
export function RafScoreBadge({
  score,
  size = "md",
  showLabel = false,
  showRisk = false,
  showBlend = false,
  v24Score,
  v28Score,
  previousScore,
  compact = false,
  className,
}: RafScoreBadgeProps) {
  // Guard: render a dash for null/NaN inputs gracefully
  if (score === null || score === undefined || Number.isNaN(score)) {
    return (
      <span
        className={cn(
          "inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs text-slate-400 dark:border-slate-700 dark:bg-slate-900",
          className,
        )}
        aria-label="RAF score not available"
      >
        —
      </span>
    );
  }

  if (compact) {
    return <CompactBadge score={score} className={className} />;
  }

  return (
    <CardGauge
      score={score}
      size={size}
      showLabel={showLabel}
      showRisk={showRisk}
      showBlend={showBlend}
      v24Score={v24Score}
      v28Score={v28Score}
      previousScore={previousScore}
      className={className}
    />
  );
}

export default RafScoreBadge;
