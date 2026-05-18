"use client";

import React from "react";

// Usage:
// import { EmptyState } from "@/components/ui/empty-state";
//
// State-aware variants:
//   state="no-data"         → "Get started by [primary CTA]"
//   state="awaiting-action" → "{count} patients need [action]" + CTA
//   state="filtered-out"    → "No matches for current filters"
//   state="complete"        → "All caught up — {count} items processed"
//
// Legacy (no state prop): title + description rendered as-is.
//
// Examples:
//   <EmptyState state="no-data" title="Connect EMR or upload a CSV to begin" cta={{ label: "Connect EMR", href: "/connect" }} />
//   <EmptyState state="awaiting-action" title="patients need analysis" count={42} cta={{ label: "Analyze Now", onClick: handleAnalyze }} />
//   <EmptyState state="filtered-out" cta={{ label: "Clear filters", onClick: clearFilters }} />
//   <EmptyState state="complete" title="items processed" count={18} />

export type EmptyStateVariant =
  | "no-data"
  | "awaiting-action"
  | "filtered-out"
  | "complete";

export interface EmptyStateCTA {
  label: string;
  href?: string;
  onClick?: () => void;
}

export interface EmptyStateProps {
  /** Semantic state — drives default copy + icon tint */
  state?: EmptyStateVariant;
  icon?: React.ReactNode;
  title?: string;
  description?: string;
  /** Used in "awaiting-action" and "complete" to interpolate count into copy */
  count?: number;
  /** Primary call-to-action rendered as a button or anchor */
  cta?: EmptyStateCTA;
}

function defaultTitle(state: EmptyStateVariant, count?: number, title?: string): string {
  switch (state) {
    case "no-data":
      return title ?? "Get started by connecting your data source";
    case "awaiting-action":
      return count !== undefined
        ? `${count} patient${count !== 1 ? "s" : ""} need${count === 1 ? "s" : ""} ${title ?? "action"}`
        : (title ?? "Patients need your attention");
    case "filtered-out":
      return "No matches for current filters";
    case "complete":
      return count !== undefined
        ? `All caught up — ${count} item${count !== 1 ? "s" : ""} processed`
        : (title ?? "All caught up");
  }
}

function stateIconTint(state: EmptyStateVariant): string {
  switch (state) {
    case "no-data":         return "text-muted-foreground";
    case "awaiting-action": return "text-amber-500";
    case "filtered-out":    return "text-muted-foreground";
    case "complete":        return "text-emerald-500";
  }
}

export function EmptyState({
  state,
  icon,
  title,
  description,
  count,
  cta,
}: EmptyStateProps) {
  const resolvedTitle = state
    ? defaultTitle(state, count, title)
    : (title ?? "");

  const iconTint = state ? stateIconTint(state) : "text-muted-foreground";

  const ctaEl = cta ? (
    cta.href ? (
      <a
        href={cta.href}
        className="inline-flex items-center justify-center rounded-lg bg-primary px-4 py-1.5 text-[13px] font-semibold text-primary-foreground hover:bg-primary/90 transition-colors"
      >
        {cta.label}
      </a>
    ) : (
      <button
        type="button"
        onClick={cta.onClick}
        className="inline-flex items-center justify-center rounded-lg bg-primary px-4 py-1.5 text-[13px] font-semibold text-primary-foreground hover:bg-primary/90 transition-colors"
      >
        {cta.label}
      </button>
    )
  ) : null;

  return (
    <div
      className="animate-fade-in flex flex-col items-center justify-center px-6 py-8 text-center border-2 border-dashed border-border rounded-2xl max-h-60"
      role="status"
      aria-label={resolvedTitle}
    >
      {icon && (
        <div className={`w-12 h-12 rounded-xl bg-muted flex items-center justify-center mb-3 ${iconTint}`}>
          {icon}
        </div>
      )}
      <h4 className="m-0 text-[14px] font-semibold text-foreground leading-snug">
        {resolvedTitle}
      </h4>
      {description && (
        <p className="mt-1.5 text-[12px] text-muted-foreground max-w-[300px] leading-relaxed">
          {description}
        </p>
      )}
      {ctaEl && <div className="mt-3">{ctaEl}</div>}
    </div>
  );
}
