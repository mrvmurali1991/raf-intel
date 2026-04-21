"use client";

/**
 * SparklineTrend — 3-point SVG sparkline (prior → current → projected).
 *
 * Usage:
 *   <SparklineTrend prior={1.2} current={1.4} projected={1.6} />
 */
export function SparklineTrend({
  prior,
  current,
  projected,
}: {
  prior: number;
  current: number;
  projected: number;
}) {
  const w = 44;
  const h = 20;
  const values = [prior, current, projected];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const xs = [0, w / 2, w];
  const ys = values.map((v) => h - ((v - min) / range) * (h - 4) - 2);
  const polyline = xs.map((x, i) => `${x},${ys[i]}`).join(" ");
  const areaPath = `M${xs[0]},${ys[0]} L${xs[1]},${ys[1]} L${xs[2]},${ys[2]} L${w},${h} L0,${h} Z`;

  return (
    <svg
      width={w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      aria-label="RAF trend sparkline"
      className="flex-shrink-0"
    >
      <defs>
        <linearGradient id="sparkFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#64748b" stopOpacity="0.25" />
          <stop offset="100%" stopColor="#64748b" stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <path d={areaPath} fill="url(#sparkFill)" />
      <polyline
        points={polyline}
        fill="none"
        stroke="#64748b"
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {/* terminal dot */}
      <circle cx={xs[2]} cy={ys[2]} r="2" fill="#64748b" />
    </svg>
  );
}
