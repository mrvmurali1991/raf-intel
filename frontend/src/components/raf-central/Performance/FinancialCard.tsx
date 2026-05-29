"use client";

import { Separator } from "@/components/ui/separator";
import type { FinancialImpact } from "../_shared";
import { FinancialAreaChart } from "./FinancialAreaChart";
import { formatCurrency, formatPercent } from "@/lib/format";

/**
 * FinancialSection (FinancialCard) — current vs projected annual revenue section for panel layout.
 *
 * Layout:
 *   Current Annual    →    Projected Annual
 *   $29,741                $32,174
 *
 *   Potential Uplift
 *   +$2,433/yr
 *   +$203/mo · 8.2%
 */
export function FinancialSection({ financial }: { financial: FinancialImpact }) {
  const gain = financial.annual_delta;
  const pct = financial.current_raf
    ? ((financial.projected_raf - financial.current_raf) / financial.current_raf) * 100
    : 0;
  const hasUplift = gain > 0;

  const currentAnnual = Math.round(financial.current_annual ?? 0);
  const projectedAnnual = Math.round(financial.projected_annual ?? 0);
  const gainRounded = Math.round(gain);
  const pmpmRounded = Math.round(financial.pmpm_delta ?? 0);

  return (
    <div className="space-y-3 pt-1">
      {/* Current → Projected row — two columns with arrow separator */}
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
        <div>
          <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground mb-0.5">
            Current Annual
          </div>
          <div className="text-lg font-bold tabular-nums text-foreground">
            {formatCurrency(currentAnnual)}
          </div>
        </div>
        <span className="text-muted-foreground text-sm font-medium px-1" aria-hidden="true">→</span>
        <div>
          <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground mb-0.5">
            Projected Annual
          </div>
          <div className="text-lg font-bold tabular-nums text-foreground">
            {formatCurrency(projectedAnnual)}
          </div>
        </div>
      </div>

      {hasUplift && (
        <FinancialAreaChart
          current={currentAnnual}
          projected={projectedAnnual}
        />
      )}

      {hasUplift ? (
        <>
          <Separator />
          <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 dark:border-emerald-800 dark:bg-emerald-950/30">
            <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground mb-1">
              Potential Uplift
            </div>
            {/* Stacked: annual on one line, monthly + pct on next */}
            <div className="text-base font-bold tabular-nums text-emerald-800 dark:text-emerald-200 leading-tight">
              {formatCurrency(gainRounded, { showSign: true })}/yr
            </div>
            <div className="text-xs font-medium text-muted-foreground mt-0.5">
              {formatCurrency(pmpmRounded, { showSign: true })}/mo
              <span className="mx-1.5">·</span>
              {formatPercent(pct, { decimals: 1 })}
            </div>
          </div>
        </>
      ) : null}
      <div className="text-[10px] text-muted-foreground">
        {formatCurrency(financial.revenue_per_raf_point ?? 0)}/RAF point · CMS MA benchmark
      </div>
    </div>
  );
}
