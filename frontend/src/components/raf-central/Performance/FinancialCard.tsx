"use client";

import { Separator } from "@/components/ui/separator";
import type { FinancialImpact } from "../_shared";
import { FinancialAreaChart } from "./FinancialAreaChart";

/**
 * FinancialSection (FinancialCard) — current vs projected annual revenue section for panel layout.
 */
export function FinancialSection({ financial }: { financial: FinancialImpact }) {
  const gain = financial.annual_delta;
  const pct = financial.current_raf
    ? ((financial.projected_raf - financial.current_raf) / financial.current_raf) * 100
    : 0;
  const hasUplift = gain > 0;
  return (
    <div className="space-y-3 pt-1">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            Current annual
          </div>
          <div className="text-sm font-bold tabular-nums">
            ${(financial.current_annual ?? 0).toLocaleString()}
          </div>
        </div>
        <div>
          <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            Projected annual
          </div>
          <div className="text-sm font-bold tabular-nums">
            ${(financial.projected_annual ?? 0).toLocaleString()}
          </div>
        </div>
      </div>

      {hasUplift && (
        <FinancialAreaChart
          current={financial.current_annual ?? 0}
          projected={financial.projected_annual ?? 0}
        />
      )}

      {hasUplift ? (
        <>
          <Separator />
          <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 dark:border-emerald-800 dark:bg-emerald-950/30">
            <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              Potential uplift
            </div>
            <div className="text-lg font-bold tabular-nums text-foreground">
              +${gain.toLocaleString()}
              <span className="ml-2 text-xs font-medium text-muted-foreground">
                {pct.toFixed(1)}% · ${(financial.pmpm_delta ?? 0).toLocaleString()}/mo
              </span>
            </div>
          </div>
        </>
      ) : null}
      <div className="text-[10px] text-muted-foreground">
        ${(financial.revenue_per_raf_point ?? 0).toLocaleString()}/RAF point · CMS MA benchmark
      </div>
    </div>
  );
}
