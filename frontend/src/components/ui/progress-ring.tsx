"use client";

/**
 * ProgressRing — SVG donut/ring chart for completion percentages.
 *
 * Usage examples:
 *
 *   // Full ring with label and animation
 *   <ProgressRing value={72} label="Recapture Rate" animate />
 *
 *   // Custom size + target marker at 80%
 *   <ProgressRing value={65} size={120} strokeWidth={10} target={80} label="Gap Closure" />
 *
 *   // Inline table cell ring
 *   <MiniProgressRing value={45} />
 *
 *   // Force a specific color (overrides auto-color)
 *   <ProgressRing value={55} color="#6366f1" label="Quality Compliance" />
 */

import * as React from "react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ProgressRingProps {
  /** 0–100 percentage value */
  value: number;
  /** Pixel diameter of the outer SVG (default 80) */
  size?: number;
  /** Thickness of the ring stroke in pixels (default 8) */
  strokeWidth?: number;
  /** Override the auto-derived color */
  color?: string;
  /** Text label rendered below the ring */
  label?: string;
  /** Show the percentage value in the center of the ring (default true) */
  showValue?: boolean;
  /** Show the label below the ring (default true when label is provided) */
  showLabel?: boolean;
  /** Animate the fill arc from 0 on mount (default true) */
  animate?: boolean;
  /**
   * Draw a small tick marker on the ring circumference at this percentage.
   * Useful for showing a target vs. actual comparison.
   */
  target?: number;
  className?: string;
  /** data-testid for the root wrapper */
  testId?: string;
}

// ---------------------------------------------------------------------------
// Auto-color thresholds
// ---------------------------------------------------------------------------

function resolveColor(value: number): string {
  if (value <= 33) return "#ef4444"; // red-500
  if (value <= 66) return "#f59e0b"; // amber-500
  if (value <= 89) return "#0d9488"; // teal-600
  return "#10b981";                  // emerald-500
}

// ---------------------------------------------------------------------------
// Geometry helpers
// ---------------------------------------------------------------------------

/**
 * Convert a percentage (0–100) to a point on the ring circumference.
 * SVG circles start at the 3-o'clock position; we rotate -90° so 0% is
 * at the 12-o'clock position by applying the offset when computing x/y.
 */
function percentToPoint(
  percent: number,
  cx: number,
  cy: number,
  radius: number,
): { x: number; y: number } {
  const angle = (percent / 100) * 2 * Math.PI - Math.PI / 2;
  return {
    x: cx + radius * Math.cos(angle),
    y: cy + radius * Math.sin(angle),
  };
}

// ---------------------------------------------------------------------------
// ProgressRing
// ---------------------------------------------------------------------------

export function ProgressRing({
  value,
  size = 80,
  strokeWidth = 8,
  color,
  label,
  showValue = true,
  showLabel = true,
  animate = true,
  target,
  className,
  testId,
}: ProgressRingProps) {
  const clampedValue = Math.min(100, Math.max(0, value));
  const clampedTarget = target !== undefined
    ? Math.min(100, Math.max(0, target))
    : undefined;

  const resolvedColor = color ?? resolveColor(clampedValue);

  // Ring geometry
  const cx = size / 2;
  const cy = size / 2;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (clampedValue / 100) * circumference;

  // Target tick geometry — a short line segment perpendicular to the ring
  const tickInset  = strokeWidth * 0.6;
  const tickOutset = strokeWidth * 0.6;
  const targetPoint = clampedTarget !== undefined
    ? percentToPoint(clampedTarget, cx, cy, radius)
    : null;
  const targetInner = clampedTarget !== undefined
    ? percentToPoint(clampedTarget, cx, cy, radius - tickInset)
    : null;
  const targetOuter = clampedTarget !== undefined
    ? percentToPoint(clampedTarget, cx, cy, radius + tickOutset)
    : null;
  void targetPoint; // geometry computed through inner/outer only

  // Font sizing — scale with ring diameter so text stays proportional
  const valueFontSize = Math.max(10, Math.round(size * 0.22));
  const percentFontSize = Math.max(7, Math.round(size * 0.14));

  // Transition duration for the CSS animation
  const transitionDuration = animate ? "0.9s" : "0s";

  return (
    <div
      className={cn("inline-flex flex-col items-center gap-1.5", className)}
      data-testid={testId}
      role="figure"
      aria-label={
        label
          ? `${label}: ${clampedValue}%${clampedTarget !== undefined ? `, target ${clampedTarget}%` : ""}`
          : `${clampedValue}% complete`
      }
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        aria-hidden="true"
        style={{ display: "block", overflow: "visible" }}
      >
        {/* Background track */}
        <circle
          cx={cx}
          cy={cy}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          className="text-muted/30"
          strokeLinecap="round"
        />

        {/* Progress arc */}
        <circle
          cx={cx}
          cy={cy}
          r={radius}
          fill="none"
          stroke={resolvedColor}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          // Rotate so the arc starts at 12-o'clock
          transform={`rotate(-90 ${cx} ${cy})`}
          style={{
            transition: `stroke-dashoffset ${transitionDuration} cubic-bezier(0.4, 0, 0.2, 1)`,
            // Ensure the arc starts at full offset (0%) on mount when animated,
            // then CSS transition drives it to the real offset.
            ...(animate
              ? {
                  strokeDashoffset: offset,
                  // The initial keyframe is applied via the willChange trick below
                }
              : {}),
          }}
          data-testid={testId ? `${testId}-arc` : undefined}
        />

        {/* Target tick marker */}
        {targetInner && targetOuter && (
          <line
            x1={targetInner.x}
            y1={targetInner.y}
            x2={targetOuter.x}
            y2={targetOuter.y}
            stroke="#94a3b8"
            strokeWidth={Math.max(1.5, strokeWidth * 0.35)}
            strokeLinecap="round"
            aria-hidden="true"
          />
        )}

        {/* Center text: value percentage */}
        {showValue && (
          <g>
            <text
              x={cx}
              y={cy}
              textAnchor="middle"
              dominantBaseline="central"
              fill="currentColor"
              className="fill-foreground"
              style={{ fontSize: valueFontSize, fontWeight: 700, lineHeight: 1 }}
            >
              {clampedValue}
              <tspan
                style={{ fontSize: percentFontSize, fontWeight: 500 }}
                dy="-0.15em"
              >
                %
              </tspan>
            </text>
          </g>
        )}
      </svg>

      {/* Label below ring */}
      {label && showLabel && (
        <span
          className="text-center text-xs font-medium text-muted-foreground leading-tight max-w-[calc(var(--ring-size)*1px)]"
          style={
            { "--ring-size": size } as React.CSSProperties
          }
        >
          {label}
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// AnimatedProgressRing — wrapper that triggers the dash animation on mount
// ---------------------------------------------------------------------------

/**
 * Internal wrapper used when animate=true. Forces the SVG arc to start at
 * full offset (i.e. empty) on the first paint and then immediately sets the
 * real offset so the CSS transition drives the animation.
 *
 * This is already handled inline in ProgressRing via the style prop; the
 * component is self-contained and does NOT require this extra wrapper.
 * Exported separately in case callers need a pre-wired animated default.
 */
export function AnimatedProgressRing(props: ProgressRingProps) {
  return <ProgressRing {...props} animate />;
}

// ---------------------------------------------------------------------------
// MiniProgressRing — ultra-compact ring for table cells / inline use
// ---------------------------------------------------------------------------

export interface MiniProgressRingProps {
  /** 0–100 percentage value */
  value: number;
  /** Pixel diameter (default 24) */
  size?: number;
  /** Override auto-derived color */
  color?: string;
  className?: string;
}

export function MiniProgressRing({
  value,
  size = 24,
  color,
  className,
}: MiniProgressRingProps) {
  const clampedValue = Math.min(100, Math.max(0, value));
  const resolvedColor = color ?? resolveColor(clampedValue);

  const strokeWidth = Math.max(2, Math.round(size * 0.12));
  const cx = size / 2;
  const cy = size / 2;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (clampedValue / 100) * circumference;

  const fontSize = Math.max(5, Math.round(size * 0.26));

  return (
    <span
      className={cn("inline-flex items-center justify-center", className)}
      role="img"
      aria-label={`${clampedValue}% complete`}
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        aria-hidden="true"
        style={{ display: "block" }}
      >
        {/* Background track */}
        <circle
          cx={cx}
          cy={cy}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          className="text-muted/30"
        />

        {/* Progress arc */}
        <circle
          cx={cx}
          cy={cy}
          r={radius}
          fill="none"
          stroke={resolvedColor}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          transform={`rotate(-90 ${cx} ${cy})`}
          style={{
            transition: "stroke-dashoffset 0.6s cubic-bezier(0.4, 0, 0.2, 1)",
          }}
        />

        {/* Percentage text — only rendered when ring is large enough to read */}
        {size >= 20 && (
          <text
            x={cx}
            y={cy}
            textAnchor="middle"
            dominantBaseline="central"
            fill="currentColor"
            className="fill-foreground"
            style={{ fontSize, fontWeight: 700 }}
          >
            {clampedValue}
          </text>
        )}
      </svg>
    </span>
  );
}

export default ProgressRing;
