"use client";

import type { MEATEvidence } from "@/types";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

const letters: { key: keyof MEATEvidence; label: string; full: string }[] = [
  { key: "monitor", label: "M", full: "Monitor" },
  { key: "evaluate", label: "E", full: "Evaluate" },
  { key: "assess", label: "A", full: "Assess" },
  { key: "treat", label: "T", full: "Treat" },
];

export function MEATBadge({ evidence }: { evidence?: MEATEvidence | null }) {
  return (
    <div className="flex gap-0.5">
      {letters.map(({ key, label, full }) => {
        const filled = evidence && evidence[key];
        return (
          <Tooltip key={key}>
            <TooltipTrigger
              className={cn(
                "inline-flex h-6 w-6 items-center justify-center rounded text-xs font-bold",
                filled
                  ? "bg-emerald-500 text-white"
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
