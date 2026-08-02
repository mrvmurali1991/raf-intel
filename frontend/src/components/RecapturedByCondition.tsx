"use client";

/**
 * Side-by-side horizontal bar chart of top conditions:
 * left = $ recaptured, right = $ at risk.  Pulls from the CFO summary.
 */

import React from "react";
import { useQuery } from "@tanstack/react-query";

import { getCfoSummary, type CfoExecutiveSummary } from "@/lib/api";

function formatUSD(n: number): string {
  if (!Number.isFinite(n)) return "$0";
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(1)}k`;
  return `$${Math.round(n).toLocaleString()}`;
}

interface BarProps {
  label: string;
  sub: string;
  amount: number;
  max: number;
  color: string;
  align: "left" | "right";
}

function Bar({ label, sub, amount, max, color, align }: BarProps) {
  const pct = max > 0 ? (amount / max) * 100 : 0;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between text-xs text-slate-700 dark:text-slate-200">
        <span className="font-semibold">{label}</span>
        <span className="tabular-nums text-slate-500 dark:text-slate-400">{sub}</span>
      </div>
      <div
        className="bg-slate-100 dark:bg-slate-800 rounded-md h-2.5 overflow-hidden flex"
        style={{ flexDirection: align === "right" ? "row-reverse" : "row" }}
      >
        <div
          style={{
            width: `${Math.max(2, pct)}%`,
            background: color,
            height: "100%",
            transition: "width 0.4s ease",
          }}
        />
      </div>
      <div
        className="text-xs font-bold text-slate-900 dark:text-slate-50 tabular-nums"
        style={{ textAlign: align === "right" ? "right" : "left" }}
      >
        {formatUSD(amount)}
      </div>
    </div>
  );
}

interface Props {
  year?: number;
}

export default function RecapturedByCondition({ year }: Props) {
  const yr = year ?? new Date().getFullYear();
  const { data, isLoading, isError } = useQuery<CfoExecutiveSummary>({
    queryKey: ["cfo-summary", yr],
    queryFn: () => getCfoSummary(yr),
  });

  if (isLoading) {
    return (
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-[10px] p-4 h-[220px]" />
    );
  }
  if (isError || !data) return null;

  const recap = data.top_3_recaptured_conditions;
  const risk = data.top_3_at_risk_conditions;
  const maxRecap = Math.max(1, ...recap.map((c) => c.dollars));
  const maxRisk = Math.max(1, ...risk.map((c) => c.dollars));

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-[10px] p-4">
      <div className="flex items-center justify-between mb-3 text-[13px] font-semibold text-slate-700 dark:text-slate-200">
        <span>Recaptured by condition (top 3)</span>
        <span className="text-slate-500 dark:text-slate-400">vs $ at risk</span>
      </div>

      <div className="grid grid-cols-2 gap-6">
        <div className="flex flex-col gap-3">
          <div className="text-[11px] text-emerald-500 dark:text-emerald-400 font-bold uppercase">
            $ Recaptured
          </div>
          {recap.length === 0 ? (
            <div className="text-xs text-slate-500 dark:text-slate-400">No closures yet this year.</div>
          ) : (
            recap.map((c) => (
              <Bar
                key={`recap-${c.hcc_code}`}
                label={c.description}
                sub={`HCC ${c.hcc_code} · ${c.count}`}
                amount={c.dollars}
                max={maxRecap}
                color="#10B981"
                align="left"
              />
            ))
          )}
        </div>

        <div className="flex flex-col gap-3">
          <div className="text-[11px] text-red-500 dark:text-red-400 font-bold uppercase text-right">
            $ At Risk
          </div>
          {risk.length === 0 ? (
            <div className="text-xs text-slate-500 dark:text-slate-400 text-right">
              No open gaps.
            </div>
          ) : (
            risk.map((c) => (
              <Bar
                key={`risk-${c.hcc_code}`}
                label={c.description}
                sub={`HCC ${c.hcc_code} · ${c.count}`}
                amount={c.dollars}
                max={maxRisk}
                color="#EF4444"
                align="right"
              />
            ))
          )}
        </div>
      </div>
    </div>
  );
}
