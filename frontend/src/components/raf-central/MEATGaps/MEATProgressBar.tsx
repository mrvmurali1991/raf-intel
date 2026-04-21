"use client";

import { cn } from "@/lib/utils";
import type { MEATGap } from "../_shared";

/**
 * MEATProgressBar — thin 4-slot completion bar for an HCC card.
 */
export function MEATProgressBar({ gaps }: { gaps: MEATGap["gaps"] }) {
  const total = 4;
  const done = [gaps.monitor, gaps.evaluate, gaps.assess, gaps.treat].filter(Boolean).length;
  const pct = (done / total) * 100;
  const barColor =
    done === 4
      ? "bg-emerald-500"
      : done >= 1
      ? "bg-amber-500"
      : "bg-red-400";

  return (
    <div className="mt-2">
      <div className="h-1 w-full rounded-full bg-muted overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-[width] duration-700", barColor)}
          style={{ width: `${pct}%` }}
          role="progressbar"
          aria-valuenow={done}
          aria-valuemin={0}
          aria-valuemax={total}
          aria-label={`MEAT completion ${done}/4`}
        />
      </div>
    </div>
  );
}
