"use client";

import type { MEATEvidence } from "@/types";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

const letters: { key: keyof MEATEvidence; label: string; full: string; filledColor: string; filledBg: string }[] = [
  { key: "monitor", label: "M", full: "Monitor", filledColor: "text-teal-700 dark:text-teal-200", filledBg: "bg-teal-500 dark:bg-teal-600" },
  { key: "evaluate", label: "E", full: "Evaluate", filledColor: "text-purple-700 dark:text-purple-200", filledBg: "bg-purple-500 dark:bg-purple-600" },
  { key: "assess", label: "A", full: "Assess", filledColor: "text-amber-700 dark:text-amber-200", filledBg: "bg-amber-500 dark:bg-amber-600" },
  { key: "treat", label: "T", full: "Treat", filledColor: "text-green-700 dark:text-green-200", filledBg: "bg-green-500 dark:bg-green-600" },
];

export function MEATBadge({ evidence }: { evidence?: MEATEvidence | null }) {
  return (
    <div className="flex gap-1">
      {letters.map(({ key, label, full, filledBg }) => {
        const filled = evidence && evidence[key];
        return (
          <Tooltip key={key}>
            <TooltipTrigger
              className={cn(
                "inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold transition-all duration-150 hover:scale-110",
                filled
                  ? `${filledBg} text-white shadow-sm`
                  : "bg-muted text-muted-foreground"
              )}
            >
              {label}
            </TooltipTrigger>
            <TooltipContent>
              <p className="font-medium">{full}</p>
              {filled ? (
                <p className="max-w-xs text-xs">{evidence[key]}</p>
              ) : (
                <p className="text-xs text-muted-foreground">No evidence</p>
              )}
            </TooltipContent>
          </Tooltip>
        );
      })}
    </div>
  );
}
