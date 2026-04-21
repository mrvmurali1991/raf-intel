"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

/**
 * AuditDonut — SVG donut chart showing MEAT compliance percentage.
 */
export function AuditDonut({
  compliant,
  total,
  riskLevel,
}: {
  compliant: number;
  total: number;
  riskLevel: "LOW" | "MEDIUM" | "HIGH";
}) {
  const [animated, setAnimated] = useState(false);
  useEffect(() => {
    const t = requestAnimationFrame(() => setAnimated(true));
    return () => cancelAnimationFrame(t);
  }, []);

  // riskLevel is accepted but pct-derived coloring is the primary signal
  void riskLevel;

  const size = 88;
  const strokeWidth = 9;
  const r = (size - strokeWidth) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const circumference = 2 * Math.PI * r;
  const pct = total > 0 ? compliant / total : 0;
  const pctNum = Math.round(pct * 100);
  const dashOffset = circumference * (1 - (animated ? pct : 0));

  // Color semantics: emerald >=90%, amber 70-89%, red <70%
  const arcColor =
    pctNum >= 90 ? "#10b981" : pctNum >= 70 ? "#f59e0b" : "#ef4444";
  const riskBg =
    pctNum >= 90
      ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
      : pctNum >= 70
      ? "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300"
      : "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300";

  return (
    <div className="flex items-center gap-4">
      <div className="relative flex-shrink-0" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90" aria-hidden="true">
          <circle
            cx={cx} cy={cy} r={r}
            fill="none" stroke="currentColor"
            strokeWidth={strokeWidth}
            className="text-muted/40"
          />
          <circle
            cx={cx} cy={cy} r={r}
            fill="none"
            stroke={arcColor}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={dashOffset}
            style={{ transition: "stroke-dashoffset 0.9s ease-out" }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-lg font-bold tabular-nums text-foreground leading-none">
            {pctNum}%
          </span>
          <span className="text-[10px] text-muted-foreground leading-tight">
            {compliant}/{total}
          </span>
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        <div className="text-xs text-muted-foreground">MEAT compliance</div>
        <div className="text-sm font-bold text-foreground">
          {compliant}/{total} HCCs
        </div>
        <span className={cn("inline-flex w-fit rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide", riskBg)}>
          {pctNum >= 90 ? "LOW" : pctNum >= 70 ? "MEDIUM" : "HIGH"} RISK
        </span>
      </div>
    </div>
  );
}
