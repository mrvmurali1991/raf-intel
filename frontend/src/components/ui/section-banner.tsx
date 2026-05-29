"use client";

// SectionBanner — slim inline notice for section-level "nothing to show" states.
//
// Use this instead of <EmptyState> when the context is a *section* inside a
// larger page (e.g. "No medications" inside the Clinical tab). Reserve the full
// <EmptyState> (card with icon, title, description, CTA) for page-level empty
// states only ("No patients found", "No audit packages").
//
// Max height: ~48px. No large icon, no paragraph copy.
//
// Usage:
//   import { SectionBanner } from "@/components/ui/section-banner";
//
//   <SectionBanner message="No active medications for this patient." />
//   <SectionBanner message="No vitals recorded." variant="success" />
//   <SectionBanner message="All prior-year HCCs recaptured." variant="success" />

import React from "react";
import { Info, CheckCircle2 } from "lucide-react";

export interface SectionBannerProps {
  message: string;
  /** "info" (default muted) — nothing to worry about, just empty.
   *  "success" — green tint, signals a positive "all done" state. */
  variant?: "info" | "success";
  className?: string;
}

export function SectionBanner({
  message,
  variant = "info",
  className = "",
}: SectionBannerProps) {
  if (variant === "success") {
    return (
      <div
        role="status"
        aria-label={message}
        className={`flex items-center gap-2 px-4 py-3 bg-emerald-50 dark:bg-emerald-950/30 rounded-lg text-sm text-emerald-700 dark:text-emerald-300 ${className}`}
      >
        <CheckCircle2 size={15} className="shrink-0 text-emerald-500" aria-hidden />
        <span>{message}</span>
      </div>
    );
  }

  return (
    <div
      role="status"
      aria-label={message}
      className={`flex items-center gap-2 px-4 py-3 bg-muted/50 rounded-lg text-sm text-muted-foreground ${className}`}
    >
      <Info size={15} className="shrink-0" aria-hidden />
      <span>{message}</span>
    </div>
  );
}
