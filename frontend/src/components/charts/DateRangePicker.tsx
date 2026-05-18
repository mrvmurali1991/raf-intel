"use client";

/**
 * DateRangePicker — preset selector (7d / 30d / 90d / PYTD / custom) + custom
 * date inputs. Fully controlled; caller owns state.
 *
 * Usage:
 *   const [range, setRange] = useState<DateRange>({ preset: "30d" });
 *   <DateRangePicker value={range} onChange={setRange} />
 */

import React, { useState, useEffect } from "react";
import { Calendar } from "lucide-react";

export type PresetKey = "7d" | "30d" | "90d" | "pytd" | "custom";

export interface DateRange {
  preset: PresetKey;
  /** ISO date string YYYY-MM-DD (only used when preset === "custom") */
  from?: string;
  to?: string;
}

export interface DateRangePickerProps {
  value: DateRange;
  onChange: (range: DateRange) => void;
  /** Optional extra class on the root wrapper */
  className?: string;
}

const PRESETS: { key: PresetKey; label: string }[] = [
  { key: "7d", label: "Last 7d" },
  { key: "30d", label: "Last 30d" },
  { key: "90d", label: "Last 90d" },
  { key: "pytd", label: "PYTD" },
  { key: "custom", label: "Custom" },
];

/** Returns { from, to } ISO strings for a given preset. */
export function presetToDates(preset: PresetKey): { from: string; to: string } {
  const today = new Date();
  const fmt = (d: Date) => d.toISOString().slice(0, 10);
  const sub = (days: number) => {
    const d = new Date(today);
    d.setDate(d.getDate() - days);
    return d;
  };

  if (preset === "7d") return { from: fmt(sub(6)), to: fmt(today) };
  if (preset === "30d") return { from: fmt(sub(29)), to: fmt(today) };
  if (preset === "90d") return { from: fmt(sub(89)), to: fmt(today) };
  if (preset === "pytd") {
    // Prior year to date: Jan 1 of last year → same calendar day last year
    const prevYear = today.getFullYear() - 1;
    return {
      from: `${prevYear}-01-01`,
      to: `${prevYear}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`,
    };
  }
  // custom — caller supplies
  return { from: fmt(sub(29)), to: fmt(today) };
}

export function DateRangePicker({ value, onChange, className }: DateRangePickerProps) {
  // Local custom date state — only committed on blur/change
  const [customFrom, setCustomFrom] = useState(value.from ?? "");
  const [customTo, setCustomTo] = useState(value.to ?? "");

  // Keep custom inputs in sync when preset changes externally
  useEffect(() => {
    if (value.preset !== "custom") {
      const { from, to } = presetToDates(value.preset);
      setCustomFrom(from);
      setCustomTo(to);
    } else {
      if (value.from) setCustomFrom(value.from);
      if (value.to) setCustomTo(value.to);
    }
  }, [value.preset, value.from, value.to]);

  function selectPreset(key: PresetKey) {
    if (key === "custom") {
      onChange({ preset: "custom", from: customFrom, to: customTo });
    } else {
      const { from, to } = presetToDates(key);
      onChange({ preset: key, from, to });
    }
  }

  function commitCustom() {
    if (customFrom && customTo && customFrom <= customTo) {
      onChange({ preset: "custom", from: customFrom, to: customTo });
    }
  }

  return (
    <div
      className={["inline-flex items-center gap-2 flex-wrap", className].filter(Boolean).join(" ")}
      role="group"
      aria-label="Date range selector"
    >
      {/* Calendar icon */}
      <Calendar size={15} className="text-muted-foreground shrink-0" aria-hidden="true" />

      {/* Preset pills */}
      <div className="inline-flex gap-1 bg-secondary rounded-lg p-[3px]">
        {PRESETS.map((p) => {
          const active = value.preset === p.key;
          return (
            <button
              key={p.key}
              onClick={() => selectPreset(p.key)}
              aria-pressed={active}
              className={[
                "px-3 py-[5px] text-xs rounded-md border-none cursor-pointer transition-colors duration-150 whitespace-nowrap",
                active
                  ? "bg-primary text-primary-foreground font-bold"
                  : "bg-transparent text-muted-foreground font-medium hover:bg-accent hover:text-accent-foreground",
              ].join(" ")}
            >
              {p.label}
            </button>
          );
        })}
      </div>

      {/* Custom date inputs — visible only when preset === "custom" */}
      {value.preset === "custom" && (
        <div className="inline-flex items-center gap-1.5">
          <input
            type="date"
            value={customFrom}
            max={customTo || undefined}
            onChange={(e) => setCustomFrom(e.target.value)}
            onBlur={commitCustom}
            aria-label="Start date"
            className="px-[10px] py-[5px] text-xs font-medium border border-border rounded-md bg-input text-foreground outline-none cursor-pointer focus:ring-2 focus:ring-ring"
          />
          <span className="text-xs text-muted-foreground font-semibold">to</span>
          <input
            type="date"
            value={customTo}
            min={customFrom || undefined}
            onChange={(e) => setCustomTo(e.target.value)}
            onBlur={commitCustom}
            aria-label="End date"
            className="px-[10px] py-[5px] text-xs font-medium border border-border rounded-md bg-input text-foreground outline-none cursor-pointer focus:ring-2 focus:ring-ring"
          />
        </div>
      )}

      {/* Resolved date range label (non-custom) */}
      {value.preset !== "custom" && value.from && value.to && (
        <span className="text-[11px] text-muted-foreground font-medium whitespace-nowrap">
          {value.from} &rarr; {value.to}
        </span>
      )}
    </div>
  );
}

export default DateRangePicker;
