"use client";

/**
 * Sparkline split out of metric-card so recharts (~95 KB gzipped) can be
 * lazy-loaded via next/dynamic. Pages without a trend never pay this cost.
 *
 * Default-exported for clean dynamic() interop.
 */

import { Line, LineChart, ResponsiveContainer } from "recharts";

export default function MetricCardSpark({
  data,
  colour,
}: {
  data: number[];
  colour: string;
}) {
  const pts = data.map((v, i) => ({ i, v }));
  return (
    <div className="w-full h-9 mt-1" aria-hidden>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={pts}>
          <Line
            type="monotone"
            dataKey="v"
            stroke={colour}
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
