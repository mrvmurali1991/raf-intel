"use client";

/**
 * SpecialtyBenchmarkTab
 *
 * Drawer-tab content showing every provider in the same specialty cohort
 * as the currently-focused provider, with each KPI rendered as a
 * percentile-coloured chip.  The current provider's row is highlighted.
 *
 * Backed by GET /api/providers/specialty-benchmarks?year=…
 *
 * Falls back to "Insufficient peers" empty state when n<3.
 */
import React, { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  getSpecialtyBenchmarks,
  type PeerKpiKey,
} from "@/lib/api";

interface SpecialtyCohortRow {
  provider_id: number; provider_name: string; specialty: string;
  kpis: Partial<Record<PeerKpiKey, number | null>>;
  values?: Partial<Record<PeerKpiKey, number | null>>;
  percentiles: Partial<Record<PeerKpiKey, number | null>>;
}
interface SpecialtyCohort {
  specialty: string; cohort_size: number; insufficient_peers: boolean;
  cohort_summary: Partial<Record<PeerKpiKey, { min: number; median: number; max: number; n: number }>>;
  providers: SpecialtyCohortRow[];
}
interface SpecialtyBenchmarks { measurement_year: number; specialties: SpecialtyCohort[] }

const COLUMNS: { key: PeerKpiKey; label: string; format: "raf" | "pct" | "usd" }[] = [
  { key: "average_raf",                 label: "Avg RAF",     format: "raf" },
  { key: "hcc_capture_rate",            label: "Capture",     format: "pct" },
  { key: "recapture_rate",              label: "Recapture",   format: "pct" },
  { key: "meat_completeness_avg",       label: "MEAT",        format: "pct" },
  { key: "revenue_opportunity",         label: "Revenue Opp", format: "usd" },
  { key: "documentation_quality_score", label: "Doc Quality", format: "pct" },
];

function fmt(value: number | null | undefined, kind: "raf" | "pct" | "usd"): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (kind === "raf") return value.toFixed(3);
  if (kind === "pct") return `${Math.round(value * 100)}%`;
  if (Math.abs(value) >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`;
  if (Math.abs(value) >= 1_000) return `$${(value / 1_000).toFixed(1)}k`;
  return `$${Math.round(value).toLocaleString()}`;
}

function chipColor(percentile: number | null): { fgClass: string; bgClass: string } {
  if (percentile === null || percentile === undefined) {
    return { fgClass: "text-slate-500 dark:text-slate-400", bgClass: "bg-slate-100 dark:bg-slate-800" };
  }
  if (percentile >= 75) return { fgClass: "text-emerald-500 dark:text-emerald-400", bgClass: "bg-emerald-50 dark:bg-emerald-950" };
  if (percentile >= 50) return { fgClass: "text-blue-600 dark:text-blue-400", bgClass: "bg-blue-50 dark:bg-blue-950" };
  if (percentile >= 25) return { fgClass: "text-amber-500 dark:text-amber-400", bgClass: "bg-amber-50 dark:bg-amber-950" };
  return { fgClass: "text-red-500 dark:text-red-400", bgClass: "bg-red-50 dark:bg-red-950" };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export interface SpecialtyBenchmarkTabProps {
  providerId: number;
  specialty: string | null | undefined;
  year?: number;
}

export default function SpecialtyBenchmarkTab({
  providerId,
  specialty,
  year,
}: SpecialtyBenchmarkTabProps) {
  const q = useQuery<SpecialtyBenchmarks>({
    queryKey: ["specialty-benchmarks", year],
    queryFn: () => getSpecialtyBenchmarks(year) as Promise<SpecialtyBenchmarks>,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: 1,
  });

  const cohort: SpecialtyCohort | null = useMemo(() => {
    if (!q.data || !specialty) return null;
    return q.data.specialties.find((s) => s.specialty === specialty) ?? null;
  }, [q.data, specialty]);

  if (q.isLoading) {
    return (
      <div className="p-[18px] text-slate-500 dark:text-slate-400 text-[13px]">
        Loading specialty benchmarks…
      </div>
    );
  }

  if (q.isError) {
    return (
      <div className="p-[18px] text-red-500 dark:text-red-400 text-[13px]">
        Specialty benchmarks unavailable. {(q.error as Error)?.message ?? ""}
      </div>
    );
  }

  if (!cohort) {
    return (
      <div className="p-[18px] text-slate-500 dark:text-slate-400 text-[13px]">
        No cohort data for{" "}
        <strong className="text-slate-700 dark:text-slate-200">{specialty ?? "this specialty"}</strong>.
      </div>
    );
  }

  if (cohort.insufficient_peers) {
    return (
      <div className="p-[18px] text-[13px]">
        <div className="font-semibold text-slate-900 dark:text-slate-50 mb-1">
          {cohort.specialty}
        </div>
        <div className="text-slate-500 dark:text-slate-400">
          Cohort has only {cohort.cohort_size} provider{cohort.cohort_size === 1 ? "" : "s"} —
          peer benchmarking requires ≥3 providers in the same specialty.
        </div>
      </div>
    );
  }

  const peerCount = Math.max(0, cohort.cohort_size - 1);

  return (
    <div className="p-[18px]">
      {/* Header */}
      <div className="flex items-baseline justify-between mb-3">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500 dark:text-slate-400">
            Specialty Cohort
          </div>
          <div className="text-base font-bold text-slate-900 dark:text-slate-50">
            {cohort.specialty}
          </div>
        </div>
        <div className="text-xs text-slate-500 dark:text-slate-400">
          {cohort.cohort_size} providers · {peerCount} peers
        </div>
      </div>

      {/* Cohort summary strip */}
      <div
        className="bg-slate-100 dark:bg-slate-800 rounded-lg mb-3.5"
        style={{
          display: "grid",
          gridTemplateColumns: `repeat(${COLUMNS.length}, minmax(0, 1fr))`,
          gap: 8,
          padding: "10px 12px",
        }}
      >
        {COLUMNS.map((c) => {
          const stat = cohort.cohort_summary[c.key];
          return (
            <div key={c.key}>
              <div className="text-[9px] font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400 mb-1">
                {c.label}
              </div>
              <div className="text-[11px] text-slate-700 dark:text-slate-200">
                <div>med {fmt(stat?.median, c.format)}</div>
                <div className="text-slate-500 dark:text-slate-400 text-[10px]">
                  {fmt(stat?.min, c.format)} – {fmt(stat?.max, c.format)}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Provider table */}
      <div className="border border-slate-200 dark:border-slate-700 rounded-lg overflow-auto">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr className="bg-slate-100 dark:bg-slate-800">
              <th className="text-left px-3 py-2 text-slate-500 dark:text-slate-400 font-semibold uppercase text-[10px] tracking-wide border-b border-slate-200 dark:border-slate-700">
                Provider
              </th>
              {COLUMNS.map((c) => (
                <th
                  key={c.key}
                  className="text-left px-2 py-2 text-slate-500 dark:text-slate-400 font-semibold uppercase text-[10px] tracking-wide border-b border-slate-200 dark:border-slate-700 whitespace-nowrap"
                >
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {cohort.providers.map((row) => (
              <ProviderRow
                key={row.provider_id}
                row={row}
                isCurrent={row.provider_id === providerId}
              />
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-2.5 text-[10px] text-slate-500 dark:text-slate-400 leading-relaxed">
        Chips encode percentile-rank inside this cohort: emerald ≥75 ·
        blue ≥50 · amber ≥25 · red &lt;25.  Higher is better for every KPI.
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ProviderRow({
  row,
  isCurrent,
}: {
  row: SpecialtyCohortRow;
  isCurrent: boolean;
}) {
  const r = row as SpecialtyCohortRow & { full_name?: string; first_name?: string; last_name?: string };
  const name = r.full_name?.trim() || `${r.first_name ?? ""} ${r.last_name ?? ""}`.trim() || row.provider_name;
  return (
    <tr
      className={`border-b border-slate-100 dark:border-slate-800 ${
        isCurrent ? "bg-blue-50 dark:bg-blue-950" : "bg-white dark:bg-slate-900"
      }`}
    >
      <td
        className={`px-3 py-2.5 whitespace-nowrap ${
          isCurrent
            ? "text-blue-600 dark:text-blue-400 font-bold"
            : "text-slate-900 dark:text-slate-50 font-semibold"
        }`}
      >
        {name || `Provider ${row.provider_id}`}
        {isCurrent && (
          <span className="ml-1.5 text-[9px] font-bold text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-950 rounded-full uppercase tracking-wide px-1.5 py-0.5">
            You
          </span>
        )}
      </td>
      {COLUMNS.map((c) => {
        const value = row.kpis[c.key] ?? null;
        const pct = row.percentiles[c.key] ?? null;
        const { fgClass, bgClass } = chipColor(pct);
        return (
          <td key={c.key} className="px-2 py-2.5 whitespace-nowrap">
            <div
              title={
                pct !== null && pct !== undefined
                  ? `${c.label}: ${Math.round(pct)}th percentile`
                  : `${c.label}: no peer data`
              }
              className={`inline-flex items-center gap-1.5 rounded-full font-bold text-[11px] px-2 py-0.5 ${bgClass} ${fgClass}`}
            >
              <span>{fmt(value, c.format)}</span>
              {pct !== null && pct !== undefined && (
                <span className="text-[9px] opacity-85 font-semibold">
                  · p{Math.round(pct)}
                </span>
              )}
            </div>
          </td>
        );
      })}
    </tr>
  );
}
