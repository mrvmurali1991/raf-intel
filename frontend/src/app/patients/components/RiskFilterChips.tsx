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
  /** Patch a subset of colFilters — used by role-based chips */
  onColFiltersChange: (patch: Partial<ColFilters>) => void;
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
  onColFiltersChange,
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

  // Role-based chip definitions — clinical job-to-be-done language.
  // Each chip maps to a preset combination of riskFilter + colFilters.
  const roleChips: {
    id: string;
    label: string;
    count: number | null;
    chipTitle: string;
    dotColor: string | null;
    isActive: boolean;
    onActivate: () => void;
  }[] = [
    {
      id: "all",
      label: "All Patients",
      count: stats.all,
      chipTitle: "Show all patients",
      dotColor: null,
      isActive: riskFilter === "all" && !hasActiveColFilters,
      onActivate: () => { onClearColFilters(); onRiskFilterChange("all"); },
    },
    {
      id: "needs-analysis",
      label: "Needs Analysis",
      count: stats.unscored,
      chipTitle: "Patients with no RAF score — pending documentation review",
      dotColor: tokens.slate400,
      isActive: riskFilter === "unscored" && !hasActiveColFilters,
      onActivate: () => { onClearColFilters(); onRiskFilterChange("unscored"); },
    },
    {
      id: "high-raf",
      label: "High RAF",
      count: stats.high,
      chipTitle: "Patients with RAF ≥ 2.0 — highest complexity, highest cost impact",
      dotColor: tokens.riskHigh,
      isActive: riskFilter === "high" && colFilters.status === "all" && !colFilters.hccMin,
      onActivate: () => { onClearColFilters(); onRiskFilterChange("high"); },
    },
    {
      id: "missing-notes",
      label: "Missing Notes",
      count: stats.unscored,
      chipTitle: "Patients without a calculated score — chart notes or encounter documentation are missing",
      dotColor: "#D97706",
      isActive: riskFilter === "all" && colFilters.status === "pending" && !colFilters.hccMin,
      onActivate: () => {
        onClearColFilters();
        onRiskFilterChange("all");
        onColFiltersChange({ status: "pending" });
      },
    },
    {
      id: "has-hccs",
      label: "Has HCCs",
      count: null,
      chipTitle: "Patients with at least one captured Hierarchical Condition Category",
      dotColor: tokens.infoBlue,
      isActive: colFilters.hccMin === "1" && riskFilter === "all",
      onActivate: () => {
        onClearColFilters();
        onRiskFilterChange("all");
        onColFiltersChange({ hccMin: "1" });
      },
    },
    {
      id: "review-pending",
      label: "Review Pending",
      count: stats.high,
      chipTitle: "High-RAF patients not yet scored — prioritise for coder sign-off",
      dotColor: "#B91C1C",
      isActive: riskFilter === "high" && colFilters.status === "pending",
      onActivate: () => {
        onClearColFilters();
        onRiskFilterChange("high");
        onColFiltersChange({ status: "pending" });
      },
    },
  ];

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
        {/* Role-based quick-filter chips */}
        {roleChips.map(({ id, label, count, chipTitle, dotColor, isActive, onActivate }) => (
          <button
            key={id}
            onClick={onActivate}
            title={chipTitle}
            aria-pressed={isActive}
            className="rci-filter-pill"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              height: 34,
              padding: "0 14px",
              borderRadius: 999,
              border: isActive ? "none" : `1px solid ${C.border}`,
              backgroundColor: isActive ? tokens.slate800 : tokens.white,
              color: isActive ? tokens.white : C.textMuted,
              fontSize: 12.5,
              fontWeight: 600,
              cursor: "pointer",
              transition: "all 0.15s ease",
              boxShadow: isActive ? "0 2px 8px rgba(15,23,42,0.18)" : "none",
            }}
          >
            {dotColor && (
              <span
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: "50%",
                  flexShrink: 0,
                  backgroundColor: isActive ? "rgba(255,255,255,0.7)" : dotColor,
                }}
              />
            )}
            {label}
            {count !== null && (
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  color: isActive ? "rgba(255,255,255,0.65)" : C.textMuted,
                  fontVariantNumeric: "tabular-nums",
                  marginLeft: -2,
                }}
              >
                {count}
              </span>
            )}
          </button>
        ))}

        <div style={{ width: 1, height: 20, backgroundColor: C.border, margin: "0 4px" }} />

        {/* Advanced filters toggle — collapsed by default */}
        <button
          title={showColumnFilters ? "Hide advanced column filters" : "Show advanced column filters"}
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
          Advanced filters
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
