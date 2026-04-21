"use client";

import { useState } from "react";
import type { MEATGap, MeatFilter } from "../_shared";
import { EmptyState } from "../common/EmptyState";
import { MEATRow } from "./MEATRow";

/**
 * MEATSection — full MEAT gaps section with priority bucketing and optional filter.
 * Used by both dashboard layout (filter controlled externally) and panel layout (internal state).
 */
export function MEATSection({
  patientId,
  year,
  gaps,
  onChange,
  filter: filterProp,
  onFilterChange,
}: {
  patientId: number;
  year?: number;
  gaps: MEATGap[];
  onChange: () => void;
  filter?: MeatFilter;
  onFilterChange?: (f: MeatFilter) => void;
}) {
  const [filterInternal, setFilterInternal] = useState<MeatFilter>("all");
  const filter = filterProp ?? filterInternal;
  const setFilter = onFilterChange ?? setFilterInternal;

  // Suppress unused warning — setFilter is passed as onFilterChange if not controlled
  void setFilter;

  if (!gaps.length)
    return (
      <EmptyState
        variant="success"
        title="All MEAT elements documented"
        subtitle="Accept a suspect below to add conditions requiring evidence."
      />
    );

  const filtered = gaps
    .filter((g) => {
      if (filter === "incomplete") return g.status !== "COMPLETE";
      return true;
    })
    .sort((a, b) => {
      if (filter === "high-impact") return b.coefficient - a.coefficient;
      return 0;
    });

  // Priority buckets: High >=0.4, Medium 0.15-0.4, Low <0.15
  const high = filtered.filter((g) => g.coefficient >= 0.4);
  const medium = filtered.filter((g) => g.coefficient >= 0.15 && g.coefficient < 0.4);
  const low = filtered.filter((g) => g.coefficient < 0.15);

  function PriorityGroup({
    label,
    dotColor,
    items,
  }: {
    label: string;
    dotColor: string;
    items: MEATGap[];
  }) {
    if (items.length === 0) return null;
    return (
      <div>
        <div className="flex items-center gap-1.5 px-1 py-2">
          <span className={`h-2 w-2 rounded-full flex-shrink-0 ${dotColor}`} aria-hidden />
          <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            {label}
          </span>
        </div>
        <div className="rounded-md overflow-hidden border border-border/40">
          {items.map((g, idx) => (
            <MEATRow
              key={`${g.hcc}-${g.patient_hcc_id}`}
              gap={g}
              patientId={patientId}
              year={year}
              onChange={onChange}
              isOdd={idx % 2 === 1}
            />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <PriorityGroup label="High Priority" dotColor="bg-red-500" items={high} />
      <PriorityGroup label="Medium Priority" dotColor="bg-amber-500" items={medium} />
      <PriorityGroup label="Low Priority" dotColor="bg-slate-400" items={low} />
    </div>
  );
}
