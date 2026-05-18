"use client";

/**
 * MetricMetaTooltip — "(i)" info button that reveals formula provenance.
 *
 * Usage:
 *   import { MetricMetaTooltip } from "@/components/ui/metric-meta-tooltip";
 *   <MetricMetaTooltip meta={data._meta} />
 *
 * Accepts a MetricMeta object (from api.ts) and renders a small Info icon
 * that opens a rich tooltip on hover/focus showing formula, payment year,
 * revenue per RAF point, last-computed timestamp, and scope.
 * Fully keyboard accessible: tabIndex, role="button", Enter/Space to toggle.
 */

import * as React from "react";
import { Info } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { MetricMeta } from "@/lib/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "Never";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "Never";
  try {
    const diff = Date.now() - d.getTime();
    const s = Math.floor(diff / 1000);
    if (s < 60) return `${s} second${s !== 1 ? "s" : ""} ago`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m} minute${m !== 1 ? "s" : ""} ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h} hour${h !== 1 ? "s" : ""} ago`;
    const days = Math.floor(h / 24);
    return `${days} day${days !== 1 ? "s" : ""} ago`;
  } catch {
    return "Never";
  }
}

function fmtDollars(n: number | null | undefined): string {
  if (n == null) return "—";
  return `$${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface MetricMetaTooltipProps {
  /**
   * MetricMeta block from the backend. When undefined/null the (i) button still
   * renders but shows a "Loading..." placeholder — keeps layout stable and lets
   * Playwright always find `data-testid="metric-meta-info"`.
   */
  meta?: MetricMeta | null;
  /** Tooltip open side (default: "top") */
  side?: "top" | "bottom" | "left" | "right";
}

export function MetricMetaTooltip({ meta, side = "top" }: MetricMetaTooltipProps) {
  const [open, setOpen] = React.useState(false);

  const toggle = () => setOpen((o) => !o);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      toggle();
    }
    if (e.key === "Escape") setOpen(false);
  };

  // Always render the popover content node so Playwright can find it in the
  // portal DOM regardless of whether meta has loaded yet.
  const content = meta ? (
    <div
      role="tooltip"
      data-testid="metric-meta-tooltip-content"
      className="flex flex-col gap-2 min-w-[220px] max-w-[300px] text-left"
    >
      {/* Formula */}
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-wider text-white/70 mb-0.5">
          Formula
        </p>
        <code className="block font-mono text-[11px] leading-snug bg-white/10 rounded px-1.5 py-1 break-all">
          {meta.formula ?? "—"}
        </code>
      </div>

      {/* Payment year */}
      <div className="flex justify-between items-center">
        <span className="text-[11px] text-white/80">Payment year</span>
        <span className="text-[11px] font-semibold tabular-nums">{meta.payment_year ?? "—"}</span>
      </div>

      {/* Revenue per RAF point — always show; fmtDollars returns "—" for null/undefined, "$0" for zero */}
      <div className="flex justify-between items-center">
        <span className="text-[11px] text-white/80">Revenue / RAF pt</span>
        <span className="text-[11px] font-semibold tabular-nums">
          {fmtDollars(meta.revenue_per_raf_point)}
        </span>
      </div>

      {/* Total RAF points */}
      {meta.total_raf_points != null && (
        <div className="flex justify-between items-center">
          <span className="text-[11px] text-white/80">Total RAF pts</span>
          <span className="text-[11px] font-semibold tabular-nums">
            {meta.total_raf_points.toLocaleString("en-US", { maximumFractionDigits: 2 })}
          </span>
        </div>
      )}

      {/* Scope */}
      {meta.scope && (
        <div className="flex justify-between items-center">
          <span className="text-[11px] text-white/80">Scope</span>
          <span className="text-[11px] font-semibold">{meta.scope}</span>
        </div>
      )}

      {/* Last computed */}
      <div className="flex justify-between items-center border-t border-white/20 pt-1.5 mt-0.5">
        <span className="text-[10px] text-white/70">Last computed</span>
        <span
          className="text-[10px] opacity-80 tabular-nums"
          title={meta.last_computed_at ?? undefined}
        >
          {relativeTime(meta.last_computed_at)}
        </span>
      </div>

      {/* Version */}
      {meta.version != null && (
        <div className="text-[9px] opacity-40 text-right -mt-1">v{meta.version}</div>
      )}
    </div>
  ) : (
    <div
      role="tooltip"
      data-testid="metric-meta-tooltip-content"
      className="text-[11px] text-white/80 min-w-[120px] text-left"
    >
      No formula metadata available yet
    </div>
  );

  return (
    // delay={0} on the Provider ensures the popup opens on the very first hover
    // without the default 600 ms grace period — critical for Playwright tests.
    <TooltipProvider delay={0}>
      <Tooltip open={open} onOpenChange={setOpen}>
        <TooltipTrigger
          aria-label="Show metric formula and computation details"
          aria-expanded={open}
          data-testid="metric-meta-info"
          onClick={toggle}
          onKeyDown={handleKeyDown}
          className="
            inline-flex items-center justify-center
            h-4 w-4 rounded-full
            text-muted-foreground hover:text-foreground
            focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1
            transition-colors duration-150
            cursor-pointer
            shrink-0
          "
        >
          <Info size={13} aria-hidden />
        </TooltipTrigger>
        <TooltipContent
          side={side}
          sideOffset={6}
          className="!max-w-none bg-foreground/95 backdrop-blur-sm px-3 py-2.5"
        >
          {content}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export default MetricMetaTooltip;
