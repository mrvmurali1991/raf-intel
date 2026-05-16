"use client";

import type { RecaptureCard as RecaptureCardType } from "../_shared";
import { EmptyState } from "../common/EmptyState";
import { RecaptureCard } from "./RecaptureCard";

/**
 * RecaptureSection — HCC leakage view: prior-year HCCs missing in the
 * current year with explicit "leakage rate" and "revenue at risk" KPIs.
 *
 * Mirrors Pareto Intelligence's HCC Leakage Analytics surface where the
 * rate (lost / coded-last-year) is shown alongside the dollar exposure so
 * a coder can immediately tell whether this patient is a one-condition
 * miss vs. a panel-wide documentation drift. The rate baseline is
 * recapture.length + (assumed-still-coded count); when the backend ships
 * a true prior-year baseline we'll source it from there.
 */
export function RecaptureSection({
  recapture,
  priorYearTotalHCCs,
}: {
  recapture: RecaptureCardType[];
  /** Optional prior-year HCC count used as the denominator for the leakage
   *  rate. When omitted we fall back to the deduped recapture count as a
   *  conservative floor so the metric is never overstated. */
  priorYearTotalHCCs?: number | null;
}) {
  if (!recapture.length)
    return (
      <EmptyState
        variant="success"
        title="No leakage — all prior-year HCCs recaptured"
        subtitle="Every condition coded in the prior payment year is documented again this year."
      />
    );

  // Dedupe by hcc+label key to prevent backend duplicates rendering in the UI
  const seen = new Set<string>();
  const deduped = recapture.filter((r) => {
    const key = `${r.hcc}-${r.label}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  const totalRisk = deduped.reduce((acc, r) => acc + (r.revenue_at_risk ?? 0), 0);
  const denom = priorYearTotalHCCs && priorYearTotalHCCs > 0 ? priorYearTotalHCCs : deduped.length;
  const leakagePct = denom > 0 ? Math.round((deduped.length / denom) * 100) : 0;
  // Recapture-rate convention: industry target ≥85% recapture (Optum
  // advisory benchmark). Render leakage in red when above 30%, amber 15-30%,
  // green ≤15%.
  const rateTone =
    leakagePct >= 30
      ? "bg-rose-50 border-rose-200 text-rose-900 dark:bg-rose-950/30 dark:text-rose-200"
      : leakagePct >= 15
      ? "bg-amber-50 border-amber-200 text-amber-900 dark:bg-amber-950/30 dark:text-amber-200"
      : "bg-emerald-50 border-emerald-200 text-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-200";
  return (
    <div className="space-y-2">
      <div className={`flex flex-wrap items-center justify-between gap-3 rounded-md border px-3 py-2 text-xs ${rateTone}`}>
        <div>
          <strong>{leakagePct}%</strong> Y/Y leakage —{" "}
          <strong>${totalRisk.toLocaleString()}</strong> revenue at risk across {deduped.length} gap
          {deduped.length === 1 ? "" : "s"}.
        </div>
        <div className="text-[10px] opacity-80">
          Industry target ≤15% leakage (≥85% recapture rate)
        </div>
      </div>
      {deduped.map((r) => (
        <RecaptureCard key={r.id} item={r} />
      ))}
    </div>
  );
}
