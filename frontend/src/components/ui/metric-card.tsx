"use client";

/**
 * MetricCard — single primitive replacing:
 *   - StatCard (healthcare-ui.tsx)
 *   - KpiCard  (RecaptureVelocityKpis.tsx)
 *   - KpiCard  (population/heatmap/page.tsx)
 *   - Inline KPI tiles in AdminDashboard.tsx
 *
 * Usage:
 *   <MetricCard label="Avg RAF" value={1.24} delta={3.2} intent="success" />
 *   <MetricCard label="Open Gaps" value={412} loading />
 *   <MetricCard label="Revenue" value="$1.2M" trend={[10,14,12,18,22]} onClick={() => router.push('/reports')} />
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { Line, LineChart, ResponsiveContainer } from "recharts";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { MetricMetaTooltip } from "@/components/ui/metric-meta-tooltip";
import type { MetricMeta } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type MetricCardIntent = "default" | "success" | "warning" | "danger";

export interface MetricCardProps {
  /** Uppercase label rendered above the value */
  label: string;
  /** Primary display value */
  value: string | number;
  /** Percentage delta — positive = up, negative = down */
  delta?: number;
  /** Array of numbers for the inline sparkline (min 2 points) */
  trend?: number[];
  /** Semantic colour intent — drives accent and delta colour */
  intent?: MetricCardIntent;
  /** Show skeleton shimmer instead of content */
  loading?: boolean;
  /** Makes the whole card an accessible button */
  onClick?: () => void;
  /**
   * Convenience: router.push(href) on click.
   * Generates an onClick handler automatically; ignored if onClick is also provided.
   * Supports query strings, e.g. "/recapture?status=open".
   */
  href?: string;
  /** Optional icon rendered in the badge tile */
  icon?: React.ReactNode;
  /** Optional sub-label (e.g. "vs last quarter") */
  subtitle?: string;
  className?: string;
  /**
   * Text link rendered BELOW the metric number — uniform CTA placement.
   * Replaces embedded buttons; displayed as "label →" in primary color.
   */
  actionLink?: { label: string; href: string };
  /**
   * When true, renders a 32 px placeholder row reserved for a MetricTrend
   * sparkline (Agent #9). Replace with <MetricTrend /> once wired.
   */
  sparklinePlaceholder?: boolean;
  /**
   * Slot for a pre-built <MetricTrend /> or custom sparkline node.
   * Takes priority over sparklinePlaceholder when both are supplied.
   */
  sparkline?: React.ReactNode;
  /**
   * MetricMeta block from the backend _meta field. When provided, renders
   * a small (i) info button in the card header that opens a formula tooltip.
   * Pass `null` to always show the (i) icon with a "Loading..." placeholder
   * (layout-stable, Playwright-reachable). Omit entirely to suppress the icon.
   */
  meta?: MetricMeta | null;
  /** data-testid placed on the label span — for smoke-test parity selectors */
  labelTestId?: string;
  /** data-testid placed on the value span — for smoke-test parity selectors */
  valueTestId?: string;
}

// ---------------------------------------------------------------------------
// Intent maps
// ---------------------------------------------------------------------------

const intentRing: Record<MetricCardIntent, string> = {
  default: "ring-foreground/10",
  success: "ring-emerald-200 dark:ring-emerald-800",
  warning: "ring-amber-200  dark:ring-amber-800",
  danger:  "ring-red-200    dark:ring-red-800",
};

const intentAccent: Record<MetricCardIntent, string> = {
  default: "bg-primary/10 text-primary",
  success: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400",
  warning: "bg-amber-100   text-amber-700  dark:bg-amber-900/40  dark:text-amber-400",
  danger:  "bg-red-100     text-red-700    dark:bg-red-900/40    dark:text-red-400",
};

const intentSpark: Record<MetricCardIntent, string> = {
  default: "hsl(var(--chart-1))",
  success: "hsl(var(--success))",
  warning: "hsl(var(--warning))",
  danger:  "hsl(var(--destructive))",
};

const intentDelta: Record<MetricCardIntent, { pos: string; neg: string; zero: string }> = {
  default: { pos: "text-emerald-600", neg: "text-red-600",   zero: "text-muted-foreground" },
  success: { pos: "text-emerald-600", neg: "text-red-600",   zero: "text-muted-foreground" },
  warning: { pos: "text-amber-600",   neg: "text-red-600",   zero: "text-muted-foreground" },
  danger:  { pos: "text-amber-600",   neg: "text-red-600",   zero: "text-muted-foreground" },
};

// ---------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------

function MetricCardSkeleton({ className }: { className?: string }) {
  return (
    <div
      aria-busy="true"
      aria-label="Loading metric"
      className={cn(
        "rounded-xl border border-border bg-card p-5 flex flex-col gap-3 animate-pulse",
        className,
      )}
    >
      <div className="flex items-center justify-between">
        <div className="h-3 w-20 rounded bg-muted/70" />
        <div className="h-10 w-10 rounded-lg bg-muted/70" />
      </div>
      <div className="h-8 w-28 rounded bg-muted/60" />
      <div className="h-3 w-32 rounded bg-muted/50" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Delta badge
// ---------------------------------------------------------------------------

function DeltaBadge({ delta, intent }: { delta: number; intent: MetricCardIntent }) {
  const colours = intentDelta[intent];
  const cls =
    delta > 0 ? colours.pos : delta < 0 ? colours.neg : colours.zero;
  const Icon =
    delta > 0 ? TrendingUp : delta < 0 ? TrendingDown : Minus;
  const sign = delta > 0 ? "+" : "";

  return (
    <span
      className={cn("inline-flex items-center gap-0.5 text-xs font-semibold tabular-nums", cls)}
      aria-label={`${sign}${delta.toFixed(1)}% change`}
    >
      <Icon size={12} aria-hidden />
      {sign}{delta.toFixed(1)}%
    </span>
  );
}

// ---------------------------------------------------------------------------
// Sparkline
// ---------------------------------------------------------------------------

function Spark({ data, colour }: { data: number[]; colour: string }) {
  const pts = data.map((v, i) => ({ i, v }));
  return (
    <div className="w-full h-9 mt-1" aria-hidden>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={pts}>
          <Line
            type="monotone"
            dataKey="v"
            stroke={colour}
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// ---------------------------------------------------------------------------
// MetricCard
// ---------------------------------------------------------------------------

export function MetricCard({
  label,
  value,
  delta,
  trend,
  intent = "default",
  loading = false,
  onClick,
  href,
  icon,
  subtitle,
  className,
  actionLink,
  sparklinePlaceholder,
  sparkline,
  meta,
  labelTestId,
  valueTestId,
}: MetricCardProps) {
  const router = useRouter();
  if (loading) return <MetricCardSkeleton className={className} />;

  const resolvedClick = onClick ?? (href ? () => router.push(href) : undefined);
  const isInteractive = Boolean(resolvedClick);

  return (
    <Card
      role={isInteractive ? "button" : undefined}
      tabIndex={isInteractive ? 0 : undefined}
      onClick={resolvedClick}
      onKeyDown={
        isInteractive
          ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); resolvedClick?.(); } }
          : undefined
      }
      aria-label={isInteractive ? `${label}: ${value}. Click to drill down.` : undefined}
      className={cn(
        // Spring hover lift — cubic-bezier(0.34, 1.56, 0.64, 1) gives the
        // spring overshoot. Multi-layer shadow builds depth.
        "transition-[box-shadow,transform] duration-200",
        "hover:shadow-[0_1px_2px_rgba(0,0,0,0.04),0_4px_16px_rgba(0,0,0,0.08),0_16px_40px_rgba(0,0,0,0.06)]",
        "hover:-translate-y-0.5 hover:scale-[1.005]",
        "active:translate-y-0 active:scale-100",
        "[transition-timing-function:cubic-bezier(0.34,1.56,0.64,1)]",
        // Per-intent ring
        intentRing[intent],
        isInteractive && "cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        className,
      )}
    >
      {/* sizing driven by CSS tokens --kpi-card-min-h / --kpi-card-pad */}
      <CardContent className="flex flex-col gap-2 min-h-[var(--kpi-card-min-h)] p-[var(--kpi-card-pad)]">
        {/* Header row: label + meta tooltip + icon badge */}
        <div className="flex items-start justify-between gap-2">
          <span
            className="flex items-center gap-1 text-label leading-none"
            data-testid={labelTestId}
          >
            {label}
            {/* Render the (i) icon whenever meta is explicitly provided,
                including null (loading state). Omitting the prop suppresses it. */}
            {meta !== undefined && <MetricMetaTooltip meta={meta} />}
          </span>
          {icon && (
            <span
              className={cn(
                "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-sm",
                intentAccent[intent],
              )}
              aria-hidden
            >
              {icon}
            </span>
          )}
        </div>

        {/* Value row */}
        <div className="flex items-end gap-2">
          <span
            className="text-metric-value leading-none text-foreground"
            data-testid={valueTestId}
          >
            {value}
          </span>
          {delta !== undefined && <DeltaBadge delta={delta} intent={intent} />}
        </div>

        {/* Subtitle */}
        {subtitle && (
          <p className="text-xs text-muted-foreground leading-snug">{subtitle}</p>
        )}

        {/* Sparkline — real node takes priority; placeholder shown when pending */}
        {sparkline ?? (trend && trend.length >= 2 ? (
          <Spark data={trend} colour={intentSpark[intent]} />
        ) : sparklinePlaceholder ? (
          <div
            aria-hidden="true"
            className="mt-auto rounded-md bg-muted/40 h-8 w-full"
          />
        ) : null)}

        {/* Action link — sits BELOW the number, never embedded as a button */}
        {actionLink && (
          <a
            href={actionLink.href}
            onClick={(e) => e.stopPropagation()}
            className="mt-auto inline-flex items-center gap-0.5 text-xs font-semibold text-primary no-underline hover:underline"
            aria-label={actionLink.label}
          >
            {actionLink.label} &rarr;
          </a>
        )}
      </CardContent>
    </Card>
  );
}

export default MetricCard;
