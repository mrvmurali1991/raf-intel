"use client";

import { CheckCircle2, Inbox } from "lucide-react";

/**
 * EmptyState — consistent "nothing here" block for section bodies.
 */
export function EmptyState({
  title,
  subtitle,
  variant = "neutral",
}: {
  title: string;
  subtitle?: string;
  variant?: "neutral" | "success";
}) {
  if (variant === "success") {
    return (
      <div className="flex flex-col items-center gap-2 py-6 text-center rounded-md bg-emerald-50 dark:bg-emerald-950/30 px-4">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-emerald-100 dark:bg-emerald-900/50 text-emerald-600 dark:text-emerald-400">
          <CheckCircle2 className="h-5 w-5" aria-hidden />
        </div>
        <div className="text-sm font-semibold text-emerald-800 dark:text-emerald-200">{title}</div>
        {subtitle ? (
          <div className="max-w-[36ch] text-xs text-emerald-700 dark:text-emerald-300">{subtitle}</div>
        ) : null}
      </div>
    );
  }
  return (
    <div className="flex flex-col items-center gap-2 py-6 text-center">
      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <Inbox className="h-5 w-5" aria-hidden />
      </div>
      <div className="text-sm font-medium text-foreground">{title}</div>
      {subtitle ? (
        <div className="max-w-[32ch] text-xs text-muted-foreground">{subtitle}</div>
      ) : null}
    </div>
  );
}
