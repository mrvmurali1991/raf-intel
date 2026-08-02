"use client";

/**
 * ProviderSuspectHotlist
 * ----------------------
 * Real-time "what should I action THIS WEEK" panel for the provider drawer.
 *
 * Backed by GET /api/providers/{id}/suspect-hotlist which returns the top
 * open suspects across the provider's panel ranked by a blended urgency
 * score (confidence + expected $ + days_open).
 */
import React from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  getProviderSuspectHotlist,
  type ProviderSuspectHotlist,
  type SuspectHotlistItem,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------
function fmt$(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `$${(n / 1_000).toFixed(1)}k`;
  return `$${Math.round(n).toLocaleString()}`;
}

function urgencyTone(score: number): {
  fgClass: string;
  bgClass: string;
  borderClass: string;
  label: string;
} {
  if (score >= 0.8) {
    return { fgClass: "text-red-600 dark:text-red-400", bgClass: "bg-red-50 dark:bg-red-950", borderClass: "border-l-red-500 dark:border-l-red-400", label: "Urgent" };
  }
  if (score >= 0.6) {
    return { fgClass: "text-amber-600 dark:text-amber-400", bgClass: "bg-amber-50 dark:bg-amber-950", borderClass: "border-l-amber-500 dark:border-l-amber-400", label: "High" };
  }
  return { fgClass: "text-blue-600 dark:text-blue-400", bgClass: "bg-blue-50 dark:bg-blue-950", borderClass: "border-l-blue-600 dark:border-l-blue-400", label: "Watch" };
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------
interface Props {
  providerId: number | string;
  year?: number;
  limit?: number;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
const CONFIDENCE_OPTIONS = [
  { label: "All", value: 0.0 },
  { label: ">= 0.50", value: 0.5 },
  { label: ">= 0.70", value: 0.7 },
  { label: ">= 0.90", value: 0.9 },
];

export default function ProviderSuspectHotlistPanel({
  providerId,
  year,
  limit = 20,
}: Props) {
  const [minConfidence, setMinConfidence] = React.useState<number>(0.0);

  const q = useQuery<ProviderSuspectHotlist>({
    queryKey: ["provider-suspect-hotlist", providerId, year, limit, minConfidence],
    queryFn: () =>
      getProviderSuspectHotlist(providerId, {
        year,
        limit,
        minConfidence,
      }),
    refetchInterval: 60_000,
    staleTime: 60_000,
    refetchOnWindowFocus: true,
  });

  return (
    <Card>
      <Header
        loading={q.isLoading}
        summary={q.data?.summary}
        minConfidence={minConfidence}
        onChangeMinConfidence={setMinConfidence}
      />

      {q.isError ? (
        <div className="p-4 text-red-600 dark:text-red-400 text-[13px]">
          Hot-list unavailable. {(q.error as Error)?.message ?? ""}
        </div>
      ) : q.isLoading ? (
        <div className="p-6 text-slate-500 dark:text-slate-400 text-[13px] text-center">
          Calculating urgency scores…
        </div>
      ) : !q.data || q.data.items.length === 0 ? (
        <EmptyState minConfidence={minConfidence} />
      ) : (
        <ItemList items={q.data.items} />
      )}

      <Footer year={q.data?.measurement_year ?? year} />
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------
function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-[10px] shadow-[0_1px_2px_rgba(15,23,42,0.04)] overflow-hidden">
      {children}
    </div>
  );
}

function Header({
  loading,
  summary,
  minConfidence,
  onChangeMinConfidence,
}: {
  loading: boolean;
  summary: ProviderSuspectHotlist["summary"] | undefined;
  minConfidence: number;
  onChangeMinConfidence: (v: number) => void;
}) {
  return (
    <div className="px-[18px] py-4 border-b border-slate-100 dark:border-slate-800 bg-slate-50 dark:bg-slate-800">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400 mb-1">
            Real-Time Suspect Hot-List
          </div>
          <div className="text-base font-bold text-slate-900 dark:text-slate-50">
            Action this week
          </div>
        </div>

        {/* Confidence filter */}
        <div
          role="radiogroup"
          aria-label="Minimum confidence filter"
          className="inline-flex bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg p-0.5"
        >
          {CONFIDENCE_OPTIONS.map((opt) => {
            const active = Math.abs(opt.value - minConfidence) < 1e-6;
            return (
              <button
                key={opt.value}
                role="radio"
                aria-checked={active}
                onClick={() => onChangeMinConfidence(opt.value)}
                className={`border-none text-[11px] font-semibold rounded-md cursor-pointer tracking-tight px-2.5 py-1 ${
                  active
                    ? "bg-blue-600 text-white"
                    : "bg-transparent text-slate-500 dark:text-slate-400"
                }`}
              >
                {opt.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Summary strip */}
      <div className="mt-3 grid grid-cols-3 gap-3">
        <Stat
          label="Open"
          value={loading ? "…" : (summary?.total_open ?? 0).toLocaleString()}
          colorClass="text-slate-900 dark:text-slate-50"
        />
        <Stat
          label={`High-Confidence (>= ${
            summary?.high_confidence_threshold
              ? Math.round(summary.high_confidence_threshold * 100)
              : 80
          }%)`}
          value={loading ? "…" : (summary?.high_confidence_count ?? 0).toLocaleString()}
          colorClass="text-emerald-600 dark:text-emerald-400"
        />
        <Stat
          label="Avg $ / Code"
          value={loading ? "…" : fmt$(summary?.avg_dollars_per_suspect ?? 0)}
          colorClass="text-blue-600 dark:text-blue-400"
        />
      </div>
    </div>
  );
}

function Stat({ label, value, colorClass }: { label: string; value: string; colorClass: string }) {
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400 mb-1">
        {label}
      </div>
      <div className={`text-base font-bold leading-tight ${colorClass}`}>
        {value}
      </div>
    </div>
  );
}

function ItemList({ items }: { items: SuspectHotlistItem[] }) {
  return (
    <ul className="list-none m-0 flex flex-col gap-2 px-3 py-3">
      {items.map((it) => (
        <SuspectCard key={it.suspect_id} item={it} />
      ))}
    </ul>
  );
}

function SuspectCard({ item }: { item: SuspectHotlistItem }) {
  const tone = urgencyTone(item.urgency_score);
  return (
    <li>
      <Link
        href={`/patients/${item.patient_id}`}
        className="block no-underline text-inherit"
      >
        <div
          className={`grid grid-cols-[1fr_auto] gap-3 items-center p-3 border border-slate-200 dark:border-slate-700 border-l-4 ${tone.borderClass} rounded-[10px] bg-white dark:bg-slate-900 transition-colors duration-[120ms] hover:bg-slate-50 dark:hover:bg-slate-800`}
        >
          <div style={{ minWidth: 0 }}>
            {/* Top row: patient + urgency tag */}
            <div className="flex items-center gap-2 mb-1.5 flex-wrap">
              <span className="text-[13px] font-bold text-slate-900 dark:text-slate-50 whitespace-nowrap overflow-hidden text-ellipsis max-w-[220px]">
                {item.patient_name}
              </span>
              <Pill
                className={`${tone.bgClass} ${tone.fgClass}`}
                label={`${tone.label} · ${(item.urgency_score * 100).toFixed(0)}`}
              />
            </div>

            {/* Bottom row: HCC chip + label + confidence + $ + days */}
            <div className="flex items-center gap-2 flex-wrap text-xs">
              <span className="inline-flex items-center bg-blue-50 dark:bg-blue-950 text-blue-600 dark:text-blue-400 rounded-md font-bold text-[11px] tracking-tight px-2 py-0.5">
                HCC {item.hcc_code}
              </span>
              <span
                className="text-slate-700 dark:text-slate-200 whitespace-nowrap overflow-hidden text-ellipsis max-w-[260px]"
                title={item.hcc_label}
              >
                {item.hcc_label}
              </span>
              {item.icd10 ? (
                <span className="text-slate-500 dark:text-slate-400 font-mono text-[11px]">
                  {item.icd10}
                </span>
              ) : null}
              <Pill
                className="bg-emerald-50 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400"
                label={`${(item.confidence * 100).toFixed(0)}% conf`}
              />
              <Pill
                className="bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200"
                label={fmt$(item.expected_dollars)}
              />
              <span className="text-slate-500 dark:text-slate-400 text-[11px]">
                {item.days_open} day{item.days_open === 1 ? "" : "s"} open
              </span>
            </div>
          </div>
        </div>
      </Link>
    </li>
  );
}

function Pill({ className, label }: { className: string; label: string }) {
  return (
    <span
      className={`inline-block rounded-full text-[11px] font-bold whitespace-nowrap px-2 py-0.5 ${className}`}
    >
      {label}
    </span>
  );
}

function EmptyState({ minConfidence }: { minConfidence: number }) {
  return (
    <div className="p-6 text-center text-slate-500 dark:text-slate-400 text-[13px]">
      {minConfidence > 0 ? (
        <>No open suspects at confidence ≥ {Math.round(minConfidence * 100)}%.</>
      ) : (
        <>No open suspects in this panel. Run a suspect scan to surface coding opportunities.</>
      )}
    </div>
  );
}

function Footer({ year }: { year: number | undefined }) {
  return (
    <div className="px-4 py-2 border-t border-slate-100 dark:border-slate-800 text-[10px] text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-800 leading-relaxed">
      Urgency = 0.5·confidence + 0.3·($/max panel $) + 0.2·(days open / 90) ·
      auto-refresh 60s{year ? ` · year ${year}` : ""}
    </div>
  );
}
