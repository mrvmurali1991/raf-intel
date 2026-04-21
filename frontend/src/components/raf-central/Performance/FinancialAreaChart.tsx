"use client";

/**
 * FinancialAreaChart — 2-point SVG area chart showing current vs projected annual revenue.
 */
export function FinancialAreaChart({
  current,
  projected,
}: {
  current: number;
  projected: number;
}) {
  const w = 100;
  const h = 44;
  const pad = 4;
  const min = Math.min(current, projected) * 0.97;
  const max = projected * 1.02;
  const range = max - min || 1;
  const toY = (v: number) => h - pad - ((v - min) / range) * (h - pad * 2);

  const x0 = pad;
  const x1 = w - pad;
  const y0 = toY(current);
  const y1 = toY(projected);

  const path = `M${x0},${y0} C${(x0 + x1) / 2},${y0} ${(x0 + x1) / 2},${y1} ${x1},${y1}`;
  const area = `M${x0},${y0} C${(x0 + x1) / 2},${y0} ${(x0 + x1) / 2},${y1} ${x1},${y1} L${x1},${h} L${x0},${h} Z`;

  return (
    <svg
      width={w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      aria-label="Financial uplift area chart"
      className="w-full"
    >
      <defs>
        <linearGradient id="finAreaGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#64748b" stopOpacity="0.18" />
          <stop offset="100%" stopColor="#64748b" stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <path d={area} fill="url(#finAreaGrad)" />
      <path d={path} fill="none" stroke="#64748b" strokeWidth="2" strokeLinecap="round" />
      <circle cx={x0} cy={y0} r="3" fill="#94a3b8" />
      <circle cx={x1} cy={y1} r="3" fill="#475569" />
    </svg>
  );
}
