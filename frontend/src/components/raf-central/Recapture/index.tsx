"use client";

import type { RecaptureCard as RecaptureCardType } from "../_shared";
import { EmptyState } from "../common/EmptyState";
import { RecaptureCard } from "./RecaptureCard";

/**
 * RecaptureSection — prior-year HCCs missing this year with revenue-at-risk summary.
 */
export function RecaptureSection({ recapture }: { recapture: RecaptureCardType[] }) {
  if (!recapture.length)
    return (
      <EmptyState
        variant="success"
        title="All recapture gaps closed"
        subtitle="Every prior-year HCC is re-documented this year."
      />
    );

  const totalRisk = recapture.reduce((acc, r) => acc + r.revenue_at_risk, 0);
  return (
    <div className="space-y-2">
      <div className="rounded-md bg-amber-50 dark:bg-amber-950/30 p-2 text-xs text-amber-900 dark:text-amber-200">
        <strong>${totalRisk.toLocaleString()}</strong> revenue at risk across {recapture.length} gaps
      </div>
      {recapture.map((r) => (
        <RecaptureCard key={r.id} item={r} />
      ))}
    </div>
  );
}
