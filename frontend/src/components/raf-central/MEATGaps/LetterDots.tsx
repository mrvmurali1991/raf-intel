"use client";

import { cn } from "@/lib/utils";
import type { MEATGap } from "../_shared";

/**
 * LetterDots — four colored circle indicators for M·E·A·T documentation status.
 */
export function LetterDots({
  gaps,
  size = "md",
}: {
  gaps: MEATGap["gaps"];
  size?: "sm" | "md";
}) {
  const items = [
    { key: "monitor", letter: "M", on: "bg-cyan-500", label: "Monitor" },
    { key: "evaluate", letter: "E", on: "bg-indigo-500", label: "Evaluate" },
    { key: "assess", letter: "A", on: "bg-amber-500", label: "Assess" },
    { key: "treat", letter: "T", on: "bg-emerald-500", label: "Treat" },
  ] as const;
  const dim = size === "sm" ? "h-4 w-4 text-[9px]" : "h-5 w-5 text-[10px]";
  return (
    <div className="flex gap-1">
      {items.map(({ key, letter, on: onColor, label }) => {
        const on = gaps[key];
        return (
          <span
            key={key}
            title={on ? `${label} documented` : `${label} missing`}
            className={cn(
              "inline-flex items-center justify-center rounded-full font-bold transition-colors",
              dim,
              on
                ? `${onColor} text-white shadow-sm`
                : "bg-muted text-muted-foreground/60 ring-1 ring-inset ring-border"
            )}
          >
            {letter}
          </span>
        );
      })}
    </div>
  );
}
