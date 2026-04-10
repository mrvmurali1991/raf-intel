"use client";

import { cn } from "@/lib/utils";

function scoreColor(score: number) {
  if (score < 1.0) return { ring: "text-emerald-500", bg: "bg-emerald-50 dark:bg-emerald-950" };
  if (score <= 1.5) return { ring: "text-amber-500", bg: "bg-amber-50 dark:bg-amber-950" };
  return { ring: "text-red-500", bg: "bg-red-50 dark:bg-red-950" };
}

export function RAFScoreDisplay({
  score,
  size = "lg",
}: {
  score: number;
  size?: "sm" | "lg";
}) {
  const { ring, bg } = scoreColor(score);
  const dim = size === "lg" ? "h-32 w-32" : "h-16 w-16";
  const textSize = size === "lg" ? "text-3xl" : "text-base";
  const labelSize = size === "lg" ? "text-xs" : "text-[10px]";

  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-full border-4",
        dim,
        bg,
        `border-current ${ring}`
      )}
    >
      <span className={cn("font-bold", textSize, ring)}>{score.toFixed(3)}</span>
      <span className={cn("text-muted-foreground", labelSize)}>RAF</span>
    </div>
  );
}
