"use client";

import { useEffect, useState } from "react";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * RAFGauge — SVG circular progress ring with animated fill and delta pill.
 *
 * Usage:
 *   <RAFGauge score={1.423} delta={0.12} year={2024} />
 */
export function RAFGauge({
  score,
  delta,
  year,
}: {
  score: number;
  delta: number | null;
  year: number;
}) {
  const [animated, setAnimated] = useState(false);
  useEffect(() => {
    const t = requestAnimationFrame(() => setAnimated(true));
    return () => cancelAnimationFrame(t);
  }, []);

  const size = 140;
  const strokeWidth = 10;
  const r = (size - strokeWidth) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const circumference = 2 * Math.PI * r;
  // Max displayable score is 2.5
  const pct = Math.min(score / 2.5, 1);
  const dashOffset = circumference * (1 - (animated ? pct : 0));

  const deltaSign = delta !== null && delta >= 0 ? "+" : "";
  const deltaColor =
    delta === null ? "text-muted-foreground" : delta > 0 ? "text-emerald-500" : "text-red-500";

  return (
    <div className="flex flex-col items-center gap-1" aria-label={`RAF score ${score.toFixed(3)}`}>
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90" aria-hidden="true">
          <defs>
            <linearGradient id="rafRingGrad" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#06b6d4" />
              <stop offset="100%" stopColor="#10b981" />
            </linearGradient>
          </defs>
          {/* Track */}
          <circle
            cx={cx}
            cy={cy}
            r={r}
            fill="none"
            stroke="currentColor"
            strokeWidth={strokeWidth}
            className="text-muted/40"
          />
          {/* Progress arc */}
          <circle
            cx={cx}
            cy={cy}
            r={r}
            fill="none"
            stroke="url(#rafRingGrad)"
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={dashOffset}
            style={{ transition: "stroke-dashoffset 1s cubic-bezier(0.34,1.56,0.64,1)" }}
          />
        </svg>
        {/* Center text — rotated back upright */}
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-[10px] font-medium uppercase tracking-widest text-muted-foreground leading-none">
            PY{year}
          </span>
          <span className="text-4xl font-bold tabular-nums leading-tight text-foreground">
            {score.toFixed(2)}
          </span>
          <span className="text-[11px] tabular-nums text-muted-foreground leading-none">
            {score.toFixed(3)}
          </span>
        </div>
      </div>
      {/* Delta pill below ring */}
      {delta !== null && (
        <span
          className={cn(
            "inline-flex items-center gap-0.5 rounded-full px-2.5 py-0.5 text-xs font-semibold tabular-nums",
            delta > 0
              ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300"
              : delta < 0
              ? "bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300"
              : "bg-muted text-muted-foreground"
          )}
        >
          {delta > 0 ? (
            <TrendingUp className="h-3 w-3" aria-hidden />
          ) : delta < 0 ? (
            <TrendingDown className="h-3 w-3" aria-hidden />
          ) : (
            <Minus className="h-3 w-3" aria-hidden />
          )}
          <span className={deltaColor}>
            {deltaSign}{delta.toFixed(3)} vs prior
          </span>
        </span>
      )}
    </div>
  );
}
