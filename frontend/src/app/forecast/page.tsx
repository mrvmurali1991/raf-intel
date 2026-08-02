"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { TrendingUp } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";

// Defer Recharts-heavy forecast card — saves ~98 kB gz on first paint.
const RAFForecastCard = dynamic(() => import("@/components/RAFForecastCard"), {
  ssr: false,
  loading: () => <div className="h-64 animate-pulse bg-muted rounded-md" />,
});

export default function ForecastDemoPage() {
  const [pid, setPid] = useState<number>(3);
  return (
    <div className="container mx-auto p-4 sm:p-6 space-y-6 max-w-5xl">
      <PageHeader
        title="RAF Financial Forecast"
        subtitle="Projected $ revenue impact if open suspects are accepted and chronic HCCs are recaptured."
        icon={<TrendingUp className="h-5 w-5" />}
      />

      <div className="flex flex-col sm:flex-row items-start sm:items-center gap-2 sm:gap-3 text-sm">
        <label htmlFor="pid" className="font-medium text-foreground">
          Patient ID
        </label>
        <input
          id="pid"
          type="number"
          value={pid}
          min={1}
          onChange={(e) => setPid(Number(e.target.value) || 1)}
          aria-label="Enter patient ID to view forecast"
          className="w-24 rounded border border-border bg-background text-foreground px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-primary/30"
        />
        <span className="text-xs text-muted-foreground">
          Try 3, 4, 5, 17 (patients with open suspects)
        </span>
      </div>

      <RAFForecastCard pid={pid} />
    </div>
  );
}
