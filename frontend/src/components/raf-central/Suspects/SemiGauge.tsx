"use client";

import { useEffect, useState } from "react";

/**
 * SemiGauge — semicircle SVG confidence gauge for suspect cards.
 *
 * Usage:
 *   <SemiGauge value={85} color="emerald" />
 */
export function SemiGauge({
  value,
  color,
}: {
  value: number; // 0-100
  color: "emerald" | "amber" | "slate";
}) {
  const [animated, setAnimated] = useState(false);
  useEffect(() => {
    const t = requestAnimationFrame(() => setAnimated(true));
    return () => cancelAnimationFrame(t);
  }, []);

  const w = 80;
  const h = 44;
  const strokeWidth = 8;
  const r = (w - strokeWidth) / 2;
  const cx = w / 2;
  const cy = h - 2;
  // Semicircle: from 180 deg to 0 deg (top arc)
  const circumference = Math.PI * r; // half circle
  const pct = value / 100;
  const dashOffset = circumference * (1 - (animated ? pct : 0));

  const strokeColor =
    color === "emerald" ? "#10b981" : color === "amber" ? "#f59e0b" : "#94a3b8";

  return (
    <div className="flex flex-col items-center" style={{ width: w }}>
      <svg
        width={w}
        height={h}
        viewBox={`0 0 ${w} ${h}`}
        aria-label={`Confidence ${value}%`}
        aria-valuenow={value}
      >
        {/* Track — semicircle */}
        <path
          d={`M${strokeWidth / 2},${cy} A${r},${r} 0 0,1 ${w - strokeWidth / 2},${cy}`}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          className="text-muted/40"
          strokeLinecap="round"
        />
        {/* Arc fill */}
        <path
          d={`M${strokeWidth / 2},${cy} A${r},${r} 0 0,1 ${w - strokeWidth / 2},${cy}`}
          fill="none"
          stroke={strokeColor}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          style={{ transition: "stroke-dashoffset 0.8s ease-out" }}
        />
      </svg>
      <span
        className="text-base font-bold tabular-nums -mt-2 leading-none"
        style={{ color: strokeColor }}
      >
        {value}%
      </span>
    </div>
  );
}
