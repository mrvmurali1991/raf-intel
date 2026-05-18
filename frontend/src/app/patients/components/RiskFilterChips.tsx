"use client";

import { Filter, FilterX } from "lucide-react";
import { tokens } from "@/styles/tokens";
import { C } from "@/lib/ui-utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type RiskFilter = "all" | "high" | "medium" | "low" | "unscored";

interface ColFilters {
  sex: "all" | "Male" | "Female";
  ageMin: string;
  ageMax: string;
  rafMin: string;
  rafMax: string;
  demoMin: string;
  demoMax: string;
  diseaseMin: string;
  diseaseMax: string;
  interactMin: string;
  interactMax: string;
  hccMin: string;
  hccMax: string;
  status: "all" | "analyzed" | "pending";
}

export interface RiskFilterChipsProps {
  stats: {
    all: number;
    high: number;
    medium: number;
    low: number;
    unscored: number;
  };
  riskFilter: RiskFilter;
  onRiskFilterChange: (f: RiskFilter) => void;
  showColumnFilters: boolean;
  onToggleColumnFilters: () => void;
  hasActiveColFilters: boolean;
  colFilters: ColFilters;
  onClearColFilters: () => void;
  isLoading: boolean;
  page: number;
  total: number;
  totalPatients: number;
  PAGE_SIZE: number;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function RiskFilterChips({
  stats,
  riskFilter,
  onRiskFilterChange,
  showColumnFilters,
  onToggleColumnFilters,
  hasActiveColFilters,
  colFilters,
  onClearColFilters,
  isLoading,
  page,
  total,
  totalPatients,
  PAGE_SIZE,
}: RiskFilterChipsProps) {
  const activeColFilterCount = [
    colFilters.sex !== "all",
    colFilters.ageMin || colFilters.ageMax,
    colFilters.rafMin || colFilters.rafMax,
    colFilters.demoMin || colFilters.demoMax,
    colFilters.diseaseMin || colFilters.diseaseMax,
    colFilters.interactMin || colFilters.interactMax,
    colFilters.hccMin || colFilters.hccMax,
    colFilters.status !== "all",
  ].filter(Boolean).length;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexWrap: "wrap",
        gap: 12,
        marginBottom: 14,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        {(
          [
            { key: "all" as const, label: "All Patients", count: stats.all, icon: null },
            { key: "high" as const, label: "High Risk", count: stats.high, icon: "⚠" },
            { key: "medium" as const, label: "Medium", count: stats.medium, icon: null },
            { key: "low" as const, label: "Low", count: stats.low, icon: null },
            { key: "unscored" as const, label: "Unscored", count: stats.unscored, icon: null },
          ] as { key: RiskFilter; label: string; count: number; icon: string | null }[]
        ).map(({ key, label, count, icon }) => {
          const active = riskFilter === key;
          const inactiveBg =
            key === "high" ? tokens.riskHighSoft :
            key === "medium" ? tokens.riskMediumSoft :
            key === "low" ? tokens.riskLowSoft :
            tokens.white;
          const inactiveBorder =
            key === "high" ? tokens.dangerBorder :
            key === "medium" ? tokens.warningBorder :
            key === "low" ? tokens.emerald100 :
            C.border;
          const inactiveColor =
            key === "high" ? "#B91C1C" :
            key === "medium" ? "#B45309" :
            key === "low" ? "#047857" :
            C.textMuted;
          const dotColor =
            key === "high" ? C.high :
            key === "medium" ? C.medium :
            key === "low" ? C.low :
            key === "unscored" ? tokens.slate300 : null;

          return (
            <button
              key={key}
              onClick={() => onRiskFilterChange(key)}
              className="rci-filter-pill"
              aria-pressed={active}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                height: 34,
                padding: "0 14px",
                borderRadius: 999,
                border: active ? "none" : `1px solid ${inactiveBorder}`,
                backgroundColor: active ? tokens.slate800 : inactiveBg,
                color: active ? tokens.white : inactiveColor,
                fontSize: 12.5,
                fontWeight: 600,
                cursor: "pointer",
                transition: "all 0.15s ease",
                boxShadow: active ? "0 2px 8px rgba(15,23,42,0.18)" : "none",
              }}
            >
              {icon && <span style={{ fontSize: 12 }}>{icon}</span>}
              {dotColor && !icon && (
                <span
                  style={{
                    width: 7,
                    height: 7,
                    borderRadius: "50%",
                    backgroundColor: dotColor,
                    boxShadow: active ? "0 0 0 2px rgba(255,255,255,0.3)" : "none",
                  }}
                />
              )}
              {label}
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  color: active ? "rgba(255,255,255,0.65)" : inactiveColor,
                  fontVariantNumeric: "tabular-nums",
                  marginLeft: -2,
                }}
              >
                {count}
              </span>
            </button>
          );
        })}

        <div style={{ width: 1, height: 20, backgroundColor: C.border, margin: "0 4px" }} />

        <button
          title={showColumnFilters ? "Hide column filters" : "Show column filters"}
          onClick={onToggleColumnFilters}
          aria-expanded={showColumnFilters}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            height: 34,
            padding: "0 14px",
            borderRadius: 999,
            border: `1px solid ${showColumnFilters || hasActiveColFilters ? C.brand : C.border}`,
            backgroundColor:
              showColumnFilters || hasActiveColFilters ? C.brandSoft : tokens.white,
            color: showColumnFilters || hasActiveColFilters ? C.brand : C.textMuted,
            fontSize: 12,
            fontWeight: 600,
            cursor: "pointer",
            transition: "all 0.15s ease",
          }}
        >
          <Filter size={13} />
          Filters
          {hasActiveColFilters && (
            <span
              style={{
                minWidth: 18,
                height: 18,
                padding: "0 5px",
                borderRadius: 9,
                backgroundColor: C.brand,
                color: "#fff",
                fontSize: 10,
                fontWeight: 700,
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {activeColFilterCount}
            </span>
          )}
        </button>
        {hasActiveColFilters && (
          <button
            onClick={onClearColFilters}
            className="inline-flex items-center gap-1.5 h-[34px] px-3 rounded-full bg-transparent border border-dashed border-slate-200 text-xs font-medium text-slate-600 cursor-pointer font-sans"
          >
            <FilterX size={12} /> Clear
          </button>
        )}
      </div>

      {!isLoading && (
        <span className="text-xs text-slate-600 whitespace-nowrap tabular-nums">
          Showing{" "}
          <strong className="text-slate-900 font-semibold">
            {Math.min(page * PAGE_SIZE + 1, total)}&ndash;
            {Math.min((page + 1) * PAGE_SIZE, total)}
          </strong>{" "}
          of <strong className="text-slate-900 font-semibold">{totalPatients.toLocaleString()}</strong>
        </span>
      )}
    </div>
  );
}
