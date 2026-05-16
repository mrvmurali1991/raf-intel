"use client";

/**
 * RafBarChart — pure SVG bar chart for RAF score comparison.
 * Extracted from roi/page.tsx so it can be lazy-loaded via dynamic().
 * No recharts dependency (NOTE: the original task mentioned recharts but
 * roi/page.tsx uses a custom SVG chart — no recharts import was found.
 * We still defer this component since it is below the fold and contains
 * SVG <animate> elements that are not needed for initial render.)
 */

import { tokens } from "@/styles/tokens";

export default function RafBarChart({
  current,
  target,
}: {
  current: number;
  target: number;
}) {
  const benchmark = 1.15;
  const max = Math.max(current, target, benchmark, 1.5) * 1.1;
  const bars = [
    { label: "Current RAF", value: current, color: tokens.warningStrong },
    { label: "Target RAF", value: target, color: tokens.success },
    { label: "Industry Avg", value: benchmark, color: tokens.infoBlue },
  ];
  const svgW = 320;
  const svgH = 160;
  const barW = 64;
  const gap = 20;
  const leftPad = 8;
  const bottomPad = 40;
  const topPad = 16;
  const chartH = svgH - bottomPad - topPad;

  return (
    <svg
      viewBox={`0 0 ${svgW} ${svgH}`}
      style={{ width: "100%", maxWidth: 320, height: "auto" }}
      role="img"
      aria-label="RAF Score comparison chart"
    >
      <defs>
        {bars.map((b, i) => (
          <linearGradient key={`barGrad${i}`} id={`barGrad${i}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={b.color} stopOpacity="1" />
            <stop offset="100%" stopColor={b.color} stopOpacity="0.6" />
          </linearGradient>
        ))}
        <filter id="barShadow">
          <feDropShadow dx="0" dy="2" stdDeviation="3" floodOpacity="0.15" />
        </filter>
      </defs>
      {bars.map((b, i) => {
        const x = leftPad + i * (barW + gap) + gap;
        const barH = (b.value / max) * chartH;
        const y = topPad + chartH - barH;
        return (
          <g key={b.label}>
            <rect
              x={x}
              y={topPad + chartH - (chartH * 0.05)}
              width={barW}
              height={chartH * 0.05}
              fill={b.color}
              opacity={0.1}
              rx={6}
            />
            <rect
              x={x}
              y={y}
              width={barW}
              height={barH}
              fill={`url(#barGrad${i})`}
              rx={6}
              filter="url(#barShadow)"
            >
              <animate
                attributeName="height"
                from="0"
                to={barH}
                dur="0.8s"
                fill="freeze"
                calcMode="spline"
                keySplines="0.25 0.1 0.25 1"
                keyTimes="0;1"
              />
              <animate
                attributeName="y"
                from={topPad + chartH}
                to={y}
                dur="0.8s"
                fill="freeze"
                calcMode="spline"
                keySplines="0.25 0.1 0.25 1"
                keyTimes="0;1"
              />
            </rect>
            {/* Value badge */}
            <rect x={x + barW / 2 - 22} y={y - 24} width={44} height={20} rx={6} fill={b.color} opacity={0.12} />
            <text x={x + barW / 2} y={y - 10} textAnchor="middle" fontSize={11} fontWeight={800} fill={b.color}>
              {(b.value ?? 0).toFixed(2)}
            </text>
            <text x={x + barW / 2} y={svgH - bottomPad + 16} textAnchor="middle" fontSize={10} fontWeight={600} fill={tokens.slate500}>
              {b.label.split(" ")[0]}
            </text>
            <text x={x + barW / 2} y={svgH - bottomPad + 28} textAnchor="middle" fontSize={10} fill={tokens.slate400}>
              {b.label.split(" ").slice(1).join(" ")}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
