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

const BASE: React.CSSProperties = {
  fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
};

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
      className={className}
      style={{ ...BASE, display: "inline-flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}
      role="group"
      aria-label="Date range selector"
    >
      {/* Calendar icon */}
      <Calendar size={15} style={{ color: "#64748B", flexShrink: 0 }} aria-hidden="true" />

      {/* Preset pills */}
      <div style={{ display: "inline-flex", gap: 4, background: "#F1F5F9", borderRadius: 8, padding: 3 }}>
        {PRESETS.map((p) => {
          const active = value.preset === p.key;
          return (
            <button
              key={p.key}
              onClick={() => selectPreset(p.key)}
              aria-pressed={active}
              style={{
                padding: "5px 12px",
                fontSize: 12,
                fontWeight: active ? 700 : 500,
                borderRadius: 6,
                border: "none",
                cursor: "pointer",
                background: active ? "#2563EB" : "transparent",
                color: active ? "#fff" : "#475569",
                transition: "background 0.15s, color 0.15s",
                whiteSpace: "nowrap",
              }}
            >
              {p.label}
            </button>
          );
        })}
      </div>

      {/* Custom date inputs — visible only when preset === "custom" */}
      {value.preset === "custom" && (
        <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <input
            type="date"
            value={customFrom}
            max={customTo || undefined}
            onChange={(e) => setCustomFrom(e.target.value)}
            onBlur={commitCustom}
            aria-label="Start date"
            style={dateInputStyle}
          />
          <span style={{ fontSize: 12, color: "#94A3B8", fontWeight: 600 }}>to</span>
          <input
            type="date"
            value={customTo}
            min={customFrom || undefined}
            onChange={(e) => setCustomTo(e.target.value)}
            onBlur={commitCustom}
            aria-label="End date"
            style={dateInputStyle}
          />
        </div>
      )}

      {/* Resolved date range label (non-custom) */}
      {value.preset !== "custom" && value.from && value.to && (
        <span style={{ fontSize: 11, color: "#94A3B8", fontWeight: 500, whiteSpace: "nowrap" }}>
          {value.from} &rarr; {value.to}
        </span>
      )}
    </div>
  );
}

const dateInputStyle: React.CSSProperties = {
  padding: "5px 10px",
  fontSize: 12,
  fontWeight: 500,
  border: "1px solid #E2E8F0",
  borderRadius: 6,
  background: "#fff",
  color: "#1E293B",
  outline: "none",
  cursor: "pointer",
};

export default DateRangePicker;
