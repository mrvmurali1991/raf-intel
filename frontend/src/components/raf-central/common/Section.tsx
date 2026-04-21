"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/**
 * Section — collapsible accordion primitive used by the panel layout.
 * Severity drives the left color rail and badge color.
 */
export function Section({
  title,
  icon,
  count,
  severity,
  defaultOpen = false,
  children,
}: {
  title: string;
  icon?: React.ReactNode;
  count?: number;
  severity: "high" | "medium" | "low";
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const rail =
    severity === "high"
      ? "border-l-red-500"
      : severity === "medium"
      ? "border-l-amber-400"
      : "border-l-slate-300 dark:border-l-slate-600";
  return (
    <div className={cn("border-l-4 bg-background", rail)}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between px-4 py-2.5 text-left hover:bg-muted/50 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
      >
        <div className="flex items-center gap-2">
          {icon}
          <span className="text-sm font-semibold">{title}</span>
          {count !== undefined ? (
            <Badge
              className={cn(
                "text-[10px] font-semibold border-0",
                count === 0
                  ? "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400"
                  : severity === "high"
                  ? "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300"
                  : severity === "medium"
                  ? "bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300"
                  : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"
              )}
            >
              {count}
            </Badge>
          ) : null}
        </div>
        <ChevronDown
          className={cn(
            "h-4 w-4 text-muted-foreground transition-transform duration-200",
            open && "rotate-180"
          )}
        />
      </button>
      {open ? <div className="px-4 pb-4 pt-1 bg-muted/20 dark:bg-muted/10">{children}</div> : null}
    </div>
  );
}
