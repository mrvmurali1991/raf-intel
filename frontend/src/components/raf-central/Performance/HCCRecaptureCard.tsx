"use client";

import { ArrowRight } from "lucide-react";
import type { FinancialImpact, AuditReadiness } from "../_shared";
import { AuditDonut } from "./AuditDonut";
import { FinancialAreaChart } from "./FinancialAreaChart";
import { formatCurrency, formatPercent } from "@/lib/format";

/**
 * HCCRecaptureCard — merged Audit + Financial card for the dashboard right column.
 * Shows MEAT compliance donut, current->projected arrow, area chart, and uplift callout.
 */
export function HCCRecaptureCard({
  audit,
  financial,
}: {
  audit: AuditReadiness;
  financial: FinancialImpact;
}) {
  const pct = financial.current_raf
    ? ((financial.projected_raf - financial.current_raf) / financial.current_raf) * 100
    : 0;

  return (
    <div className="px-4 py-3 space-y-4">
      {/* Top: MEAT compliance donut */}
      <AuditDonut
        compliant={audit.hccs_compliant}
        total={audit.hccs_total}
        riskLevel={audit.risk_level}
      />
      {/* Divider */}
      <div className="border-t border-muted/40" />
      {/* Middle: current -> projected with arrow */}
      <div className="flex items-center gap-3">
        <div>
          <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground mb-0.5">Current Annual</div>
          <div className="text-sm font-bold tabular-nums">{formatCurrency(Math.round(financial.current_annual ?? 0))}</div>
        </div>
        <ArrowRight className="h-4 w-4 text-muted-foreground flex-shrink-0" aria-hidden />
        <div>
          <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground mb-0.5">Projected Annual</div>
          <div className="text-sm font-bold tabular-nums">{formatCurrency(Math.round(financial.projected_annual ?? 0))}</div>
        </div>
      </div>
      {/* Area chart */}
      {(financial.annual_delta ?? 0) > 0 && (
        <FinancialAreaChart
          current={financial.current_annual ?? 0}
          projected={financial.projected_annual ?? 0}
        />
      )}
      {/* Potential uplift callout — stacked layout */}
      {(financial.annual_delta ?? 0) > 0 && (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950/30 px-3 py-2">
          <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground mb-1">Potential Uplift</div>
          <div className="text-base font-bold tabular-nums text-emerald-800 dark:text-emerald-200 leading-tight">
            {formatCurrency(Math.round(financial.annual_delta ?? 0), { showSign: true })}/yr
          </div>
          <div className="text-xs font-medium text-muted-foreground mt-0.5">
            {formatCurrency(Math.round(financial.pmpm_delta ?? 0), { showSign: true })}/mo
            <span className="mx-1.5">·</span>
            {formatPercent(pct, { decimals: 1 })}
          </div>
        </div>
      )}
      <div className="text-[10px] text-muted-foreground">
        {formatCurrency(financial.revenue_per_raf_point ?? 0)}/RAF point · CMS MA benchmark
      </div>
    </div>
  );
}
