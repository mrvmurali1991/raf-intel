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

function relativeTime(iso: string): string {
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const s = Math.floor(diff / 1000);
    if (s < 60) return `${s} second${s !== 1 ? "s" : ""} ago`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m} minute${m !== 1 ? "s" : ""} ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h} hour${h !== 1 ? "s" : ""} ago`;
    const d = Math.floor(h / 24);
    return `${d} day${d !== 1 ? "s" : ""} ago`;
  } catch {
    return iso;
  }
}

function fmtDollars(n: number): string {
  return `$${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface MetricMetaTooltipProps {
  meta: MetricMeta;
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

  const content = (
    <div className="flex flex-col gap-2 min-w-[220px] max-w-[300px] text-left">
      {/* Formula */}
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-wider opacity-60 mb-0.5">
          Formula
        </p>
        <code className="block font-mono text-[11px] leading-snug bg-white/10 rounded px-1.5 py-1 break-all">
          {meta.formula}
        </code>
      </div>

      {/* Payment year */}
      <div className="flex justify-between items-center">
        <span className="text-[11px] opacity-70">Payment year</span>
        <span className="text-[11px] font-semibold tabular-nums">{meta.payment_year}</span>
      </div>

      {/* Revenue per RAF point */}
      {meta.revenue_per_raf_point != null && (
        <div className="flex justify-between items-center">
          <span className="text-[11px] opacity-70">Revenue / RAF pt</span>
          <span className="text-[11px] font-semibold tabular-nums">
            {fmtDollars(meta.revenue_per_raf_point)}
          </span>
        </div>
      )}

      {/* Total RAF points */}
      {meta.total_raf_points != null && (
        <div className="flex justify-between items-center">
          <span className="text-[11px] opacity-70">Total RAF pts</span>
          <span className="text-[11px] font-semibold tabular-nums">
            {meta.total_raf_points.toLocaleString("en-US", { maximumFractionDigits: 2 })}
          </span>
        </div>
      )}

      {/* Scope */}
      {meta.scope && (
        <div className="flex justify-between items-center">
          <span className="text-[11px] opacity-70">Scope</span>
          <span className="text-[11px] font-semibold">{meta.scope}</span>
        </div>
      )}

      {/* Last computed */}
      <div className="flex justify-between items-center border-t border-white/20 pt-1.5 mt-0.5">
        <span className="text-[10px] opacity-60">Last computed</span>
        <span
          className="text-[10px] opacity-80 tabular-nums"
          title={meta.last_computed_at}
        >
          {relativeTime(meta.last_computed_at)}
        </span>
      </div>

      {/* Version */}
      <div className="text-[9px] opacity-40 text-right -mt-1">v{meta.version}</div>
    </div>
  );

  return (
    <TooltipProvider>
      <Tooltip open={open} onOpenChange={setOpen}>
        <TooltipTrigger asChild>
          <button
            type="button"
            role="button"
            tabIndex={0}
            aria-label="Show metric formula and computation details"
            aria-expanded={open}
            data-testid="revenue-at-risk-info"
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
          </button>
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
