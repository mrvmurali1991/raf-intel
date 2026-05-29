"use client";

import type { RecaptureCard as RecaptureCardType } from "../_shared";
import { formatCurrency } from "@/lib/format";

/**
 * RecaptureCard — single prior-year HCC row showing revenue at risk.
 */
export function RecaptureCard({ item }: { item: RecaptureCardType }) {
  return (
    <div className="flex items-start justify-between gap-2 py-2 border-b border-muted/40 last:border-0">
      <div className="flex-1 min-w-0">
        <div className="text-xs font-semibold truncate">{item.label}</div>
        <div className="mt-0.5 text-[11px] text-muted-foreground">
          HCC {item.hcc} · {item.icd10} · last seen {item.last_encounter_date || item.prior_year}
        </div>
      </div>
      <div className="text-xs font-bold text-amber-700 dark:text-amber-400 tabular-nums flex-shrink-0">
        {formatCurrency(Math.round(item.revenue_at_risk ?? 0))}
      </div>
    </div>
  );
}
