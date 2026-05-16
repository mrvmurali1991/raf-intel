"use client";

import { AlertTriangle } from "lucide-react";

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
        className="mt-4 flex w-full items-center justify-between gap-3 rounded-md border border-amber-300 bg-amber-50 px-4 py-2.5 text-left hover:bg-amber-100 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:border-amber-700 dark:bg-amber-950/40 dark:hover:bg-amber-950/60"
        aria-label={`Review ${actionCount} documentation gaps`}
      >
        <span className="flex items-center gap-2.5 min-w-0">
          <span className="inline-flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-amber-500 text-white shadow-sm">
            <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
          </span>
          <span className="text-sm font-semibold text-amber-900 dark:text-amber-200">
            {actionCount} gap{actionCount !== 1 ? "s" : ""} need action
          </span>
        </span>
        <span className="flex-shrink-0 text-xs font-semibold text-amber-700 dark:text-amber-300">
          Scroll to MEAT Gaps
        </span>
      </button>
    );
  }

  return (
    <button
      onClick={onClick}
      className="mx-4 my-2 flex items-center justify-between gap-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-left hover:bg-amber-100 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:border-amber-700 dark:bg-amber-950/30"
      aria-label={`Review ${actionCount} documentation gaps`}
    >
      <span className="flex items-center gap-2 min-w-0">
        <span className="inline-flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-amber-500 text-white">
          <AlertTriangle className="h-3 w-3" aria-hidden />
        </span>
        <span className="text-xs font-semibold text-amber-900 dark:text-amber-200 truncate">
          {actionCount} gap{actionCount !== 1 ? "s" : ""} need action
        </span>
      </span>
      <span className="flex-shrink-0 text-[11px] font-semibold text-amber-700 dark:text-amber-300">
        Review
      </span>
    </button>
  );
}
