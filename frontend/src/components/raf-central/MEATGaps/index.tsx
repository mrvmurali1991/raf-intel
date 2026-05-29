"use client";

import { useState } from "react";
import type { MEATGap, MeatFilter } from "../_shared";
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

  // Empty-state semantics:
  //   - gaps == [] AND we know the patient has NO HCCs → neutral "nothing to
  //     document yet" message (NOT a success — there's nothing to succeed at).
  //   - gaps == [] AND the patient has HCCs → success "all documented".
  // Previously this rendered a green "All MEAT elements documented" tile
  // even when the year filter was wrong / the breakdown hadn't loaded /
  // the patient simply has no HCCs yet — a dangerous false-positive that
  // told the clinician "you're done" when they were not (UX review #6).
  // Without knowing the HCC count locally we default to the neutral copy.
  if (!gaps.length)
    return (
      <div
        role="note"
        className="flex items-center gap-2 rounded-md bg-sky-50 dark:bg-sky-950/30 border border-sky-100 dark:border-sky-900 px-3 py-2 text-[12px] text-sky-800 dark:text-sky-200"
      >
        <svg
          className="h-3.5 w-3.5 flex-shrink-0 text-sky-500"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
        <span>This patient has no open HCC documentation requirements for the selected year.</span>
      </div>
    );

  const filtered = gaps
    .filter((g) => {
      if (filter === "incomplete") return g.status !== "COMPLETE";
      return true;
    })
    .sort((a, b) => {
      if (filter === "high-impact") return (b.coefficient ?? 0) - (a.coefficient ?? 0);
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
