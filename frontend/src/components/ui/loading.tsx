"use client";

import React from "react";
import { Loader2 } from "lucide-react";

// =============================================================================
// Unified Loading Components for RAF Intelligence
// =============================================================================
// All loading indicators should use these components for visual consistency.
// Each component respects `prefers-reduced-motion` via CSS classes defined in
// globals.css (.shimmer, .skeleton, animate-spin).
// =============================================================================

// ---------------------------------------------------------------------------
// Spinner — single spinning indicator
// ---------------------------------------------------------------------------

const SPINNER_SIZES = { sm: 16, md: 24, lg: 32 } as const;

export type SpinnerSize = keyof typeof SPINNER_SIZES;

interface SpinnerProps {
  /** sm = 16px, md = 24px, lg = 32px */
  size?: SpinnerSize;
  /** Optional CSS color override (defaults to currentColor) */
  color?: string;
  className?: string;
}

export function Spinner({ size = "md", color, className = "" }: SpinnerProps) {
  const px = SPINNER_SIZES[size];
  return (
    <Loader2
      size={px}
      color={color}
      className={`animate-spin ${className}`}
      aria-hidden="true"
      style={{ animationDuration: "0.8s" }}
    />
  );
}

// ---------------------------------------------------------------------------
// PageLoader — full-page centered spinner with optional message
// ---------------------------------------------------------------------------

interface PageLoaderProps {
  message?: string;
}

export function PageLoader({ message }: PageLoaderProps) {
  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center bg-gradient-to-br from-slate-50 via-blue-50 to-cyan-50 dark:from-slate-950 dark:via-slate-900 dark:to-slate-800 gap-3"
      role="status"
      aria-label={message ?? "Loading application"}
      aria-busy="true"
    >
      <Spinner size="lg" className="text-primary" />
      {message && (
        <p className="text-sm text-muted-foreground font-medium">{message}</p>
      )}
      <span className="sr-only">{message ?? "Loading\u2026"}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SectionLoader — inline loader with message (replaces ad-hoc spinners)
// ---------------------------------------------------------------------------

interface SectionLoaderProps {
  /** Text shown below the spinner */
  message?: string;
  /** Vertical padding in px (default 80) */
  padding?: number;
}

export function SectionLoader({
  message = "Loading data\u2026",
  padding = 80,
}: SectionLoaderProps) {
  return (
    <div
      style={{ padding: `${padding}px 0` }}
      className="flex flex-col items-center justify-center text-muted-foreground gap-3"
      role="status"
    >
      <div
        className="shimmer"
        style={{
          width: 36,
          height: 36,
          border: "3px solid var(--border, #E2E8F0)",
          borderTopColor: "var(--primary, #0EA5E9)",
          borderRadius: "50%",
        }}
      />
      <p className="text-sm font-medium">{message}</p>
      <div
        className="shimmer"
        style={{ width: 200, height: 8, borderRadius: 4 }}
      />
      <span className="sr-only">{message}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pulse — low-level shimmer rectangle (single element)
// ---------------------------------------------------------------------------

interface PulseProps {
  w: string | number;
  h: number;
  r?: number;
}

/**
 * A shimmer-animated rectangle for building skeleton layouts.
 * Respects `prefers-reduced-motion` via the `.shimmer` CSS class.
 */
export function Pulse({ w, h, r = 6 }: PulseProps) {
  return (
    <div
      className="shimmer"
      style={{
        width: w,
        height: h,
        borderRadius: r,
        background:
          "linear-gradient(90deg, #E2E8F0 25%, #EDF2F7 50%, #E2E8F0 75%)",
        backgroundSize: "200% 100%",
      }}
    />
  );
}

// ---------------------------------------------------------------------------
// SkeletonCard — reusable skeleton card (replaces KPISkeleton / Pulse cards)
// ---------------------------------------------------------------------------

interface SkeletonCardProps {
  /** Number of KPI-style cards to render in a grid row (default 4) */
  columns?: number;
  /** Gap between cards in px (default 20) */
  gap?: number;
}

export function SkeletonCard({ columns = 4, gap = 20 }: SkeletonCardProps) {
  return (
    <div
      className="kpi-strip"
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(${columns}, 1fr)`,
        gap,
      }}
    >
      {Array.from({ length: columns }).map((_, i) => (
        <div
          key={i}
          className="bg-white dark:bg-slate-900 border border-border/40 rounded-2xl p-6 shadow-sm"
        >
          <Pulse w={100} h={14} />
          <div style={{ height: 12 }} />
          <Pulse w={80} h={32} />
          <div style={{ height: 8 }} />
          <Pulse w={120} h={12} />
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// SkeletonTable — skeleton for table rows with configurable columns
// ---------------------------------------------------------------------------

interface SkeletonTableProps {
  /** Number of visible rows (default 5) */
  rows?: number;
  /** Number of columns (default 4) */
  columns?: number;
  /** Whether to show a header row (default true) */
  showHeader?: boolean;
}

export function SkeletonTable({
  rows = 5,
  columns = 4,
  showHeader = true,
}: SkeletonTableProps) {
  return (
    <div
      className="bg-white dark:bg-slate-900 border border-border/40 rounded-2xl shadow-sm overflow-hidden"
    >
      {showHeader && (
        <div
          className="border-b border-border/30"
          style={{
            display: "grid",
            gridTemplateColumns: `repeat(${columns}, 1fr)`,
            gap: 12,
            padding: "14px 20px",
          }}
        >
          {Array.from({ length: columns }).map((_, i) => (
            <Pulse key={i} w="70%" h={12} />
          ))}
        </div>
      )}
      {Array.from({ length: rows }).map((_, rowIdx) => (
        <div
          key={rowIdx}
          className="border-b border-border/20 last:border-b-0"
          style={{
            display: "grid",
            gridTemplateColumns: `repeat(${columns}, 1fr)`,
            gap: 12,
            padding: "14px 20px",
          }}
        >
          {Array.from({ length: columns }).map((_, colIdx) => (
            <Pulse
              key={colIdx}
              w={colIdx === 0 ? "85%" : `${55 + (colIdx * 10) % 30}%`}
              h={14}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ProgressBar — determinate progress bar for long operations
// ---------------------------------------------------------------------------

interface ProgressBarProps {
  /** 0-100 */
  percent: number;
  /** Optional label shown above the bar */
  label?: string;
  /** Bar height in px (default 8) */
  height?: number;
  /** Color of the filled portion (default primary) */
  color?: string;
}

export function ProgressBar({
  percent,
  label,
  height = 8,
  color,
}: ProgressBarProps) {
  const clamped = Math.max(0, Math.min(100, percent));
  return (
    <div className="w-full" role="progressbar" aria-valuenow={clamped} aria-valuemin={0} aria-valuemax={100}>
      {label && (
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs font-medium text-muted-foreground">{label}</span>
          <span className="text-xs font-semibold tabular-nums">{Math.round(clamped)}%</span>
        </div>
      )}
      <div
        className="w-full rounded-full overflow-hidden"
        style={{
          height,
          background: "var(--border, #E2E8F0)",
        }}
      >
        <div
          className="h-full rounded-full transition-[width] duration-300 ease-out"
          style={{
            width: `${clamped}%`,
            background: color ?? "var(--primary, #0EA5E9)",
          }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Backward-compatible re-exports (deprecated — use named exports above)
// ---------------------------------------------------------------------------

/** @deprecated Use `SkeletonCard` instead */
export const KPISkeleton = SkeletonCard;

/** @deprecated Use `SkeletonTable` with `showHeader={false}` instead */
export function CardSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="bg-white dark:bg-slate-900 border border-border/40 rounded-2xl p-6 shadow-sm">
      <Pulse w={180} h={18} />
      <div style={{ marginTop: 20, display: "flex", flexDirection: "column", gap: 16 }}>
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <Pulse w={60} h={14} />
            <Pulse w="100%" h={18} />
            <Pulse w={40} h={14} />
          </div>
        ))}
      </div>
    </div>
  );
}
