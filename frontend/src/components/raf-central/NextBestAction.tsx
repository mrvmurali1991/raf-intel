"use client";

import { Check } from "lucide-react";

/**
 * NextBestActionBanner — action prompt that scrolls the user to MEAT Gaps.
 * Used in both dashboard layout (emerald variant) and panel layout (neutral variant).
 */
export function NextBestActionBanner({
  actionCount,
  onClick,
  variant = "panel",
}: {
  actionCount: number;
  onClick: () => void;
  variant?: "dashboard" | "panel";
}) {
  if (variant === "dashboard") {
    return (
      <button
        onClick={onClick}
        className="mt-4 flex w-full items-center justify-between gap-3 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-left hover:bg-emerald-100 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:border-emerald-800 dark:bg-emerald-950/40 dark:hover:bg-emerald-950/60"
        aria-label={`Review ${actionCount} documentation gaps`}
      >
        <span className="flex items-center gap-2.5 min-w-0">
          <span className="inline-flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-emerald-500 text-white shadow-sm">
            <Check className="h-3.5 w-3.5" aria-hidden />
          </span>
          <span className="text-sm font-semibold text-emerald-800 dark:text-emerald-200">
            {actionCount} gap{actionCount !== 1 ? "s" : ""} require
            {actionCount === 1 ? "s" : ""} documentation review
          </span>
        </span>
        <span className="flex-shrink-0 text-xs font-semibold text-emerald-700 dark:text-emerald-300">
          Scroll to MEAT Gaps
        </span>
      </button>
    );
  }

  return (
    <button
      onClick={onClick}
      className="mx-4 my-2 flex items-center justify-between gap-3 rounded-md border bg-card px-3 py-2 text-left hover:bg-muted/50 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      aria-label={`Review ${actionCount} documentation gaps`}
    >
      <span className="flex items-center gap-2 min-w-0">
        <span className="inline-flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-emerald-500 text-white">
          <Check className="h-3 w-3" aria-hidden />
        </span>
        <span className="text-xs font-medium text-foreground truncate">
          {actionCount} gap{actionCount !== 1 ? "s" : ""} require{actionCount === 1 ? "s" : ""} documentation review
        </span>
      </span>
      <span className="flex-shrink-0 text-[11px] font-medium text-muted-foreground">
        Review
      </span>
    </button>
  );
}
