"use client";

import { useState } from "react";
import RAFForecastCard from "@/components/RAFForecastCard";

export default function ForecastDemoPage() {
  const [pid, setPid] = useState<number>(3);
  return (
    <div className="container mx-auto p-6 space-y-6">
      <header className="space-y-1 max-lg:pl-14">
        <h1 className="text-2xl font-semibold">RAF Financial Forecast</h1>
        <p className="text-sm text-slate-500">
          Projected $ revenue impact if open suspects are accepted and chronic HCCs are recaptured.
        </p>
      </header>

      <div className="flex items-center gap-3 text-sm">
        <label htmlFor="pid" className="font-medium text-slate-700">
          Patient ID
        </label>
        <input
          id="pid"
          type="number"
          value={pid}
          min={1}
          onChange={(e) => setPid(Number(e.target.value) || 1)}
          className="w-24 rounded border border-slate-300 px-2 py-1"
        />
        <span className="text-xs text-slate-400">
          Try 3, 4, 5, 17 (patients with open suspects)
        </span>
      </div>

      <RAFForecastCard pid={pid} />
    </div>
  );
}
