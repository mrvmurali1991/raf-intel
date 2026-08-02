"use client";

/**
 * Top $ HCC Opportunities card.
 *
 * Surfaces the top 5 HCCs that are NOT yet coded in this provider's panel,
 * ranked by expected $ revenue lift. Backed by
 * GET /api/providers/{id}/top-opportunities.
 */
import React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  getProviderTopHccOpportunities,
  type ProviderTopHccOpportunity,
} from "@/lib/api";

type ProviderTopHccOpportunitiesResponse = {
  opportunities: ProviderTopHccOpportunity[];
  count: number;
};

// Chart-only hex constants for dynamic bar fills
const CHART = {
  emerald500: "#10B981",
  blue600: "#2563EB",
  amber500: "#F59E0B",
};

function formatUSD(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `$${(n / 1_000).toFixed(1)}k`;
  return `$${Math.round(n).toLocaleString()}`;
}

function formatPct(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return `${Math.round(n * 100)}%`;
}

interface Props {
  providerId: number | string;
  year?: number;
  limit?: number;
}

export default function TopHccOpportunities({ providerId, year, limit = 5 }: Props) {
  const q = useQuery<ProviderTopHccOpportunitiesResponse>({
    queryKey: ["provider-top-hcc", providerId, year],
    queryFn: () => getProviderTopHccOpportunities(providerId, year, limit),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });

  if (q.isLoading) {
    return (
      <Card>
        <Header />
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Calculating top opportunities…
        </p>
      </Card>
    );
  }

  if (q.isError || !q.data) {
    return (
      <Card>
        <Header />
        <p className="text-sm text-red-500 dark:text-red-400">
          Top opportunities unavailable. {(q.error as Error)?.message ?? ""}
        </p>
      </Card>
    );
  }

  const items = q.data.opportunities ?? [];
  const totalLift = items.reduce((s, r) => s + (r.expected_lift || 0), 0);

  return (
    <Card>
      <Header totalLift={totalLift} />

      {items.length === 0 ? (
        <p className="text-xs text-slate-500 dark:text-slate-400 italic pt-2">
          No coding opportunities surfaced. Run a suspect scan to populate this
          list.
        </p>
      ) : (
        <ol className="list-none p-0 m-0 flex flex-col gap-2">
          {items.map((row, idx) => (
            <li
              key={row.hcc_code}
              className={`grid gap-3 items-center rounded-lg ${
                idx === 0
                  ? "bg-emerald-50 dark:bg-emerald-950 border border-emerald-500 dark:border-emerald-600"
                  : "bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700"
              }`}
              style={{
                gridTemplateColumns: "auto 1fr auto",
                padding: "10px 12px",
              }}
            >
              {/* HCC chip */}
              <div
                className="inline-flex items-center justify-center min-w-[48px] px-2 py-0.5 bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-600 rounded-md text-[11px] font-bold text-slate-900 dark:text-slate-50 font-mono"
                title={`HCC ${row.hcc_code}`}
              >
                HCC {row.hcc_code}
              </div>

              {/* Label + meta */}
              <div className="min-w-0">
                <div
                  className="text-[13px] font-semibold text-slate-900 dark:text-slate-50 overflow-hidden text-ellipsis whitespace-nowrap"
                  title={row.hcc_label}
                >
                  {row.hcc_label}
                </div>
                <div className="flex items-center gap-2.5 mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">
                  <span>
                    {row.patient_count_missing}{" "}
                    {row.patient_count_missing === 1 ? "patient" : "patients"}
                  </span>
                  <span className="text-slate-300 dark:text-slate-600">·</span>
                  <span>conf {formatPct(row.avg_confidence)}</span>
                  <span className="text-slate-300 dark:text-slate-600">·</span>
                  <PeerBar rate={row.peer_capture_rate} />
                </div>
              </div>

              {/* $ lift right-aligned */}
              <div className="text-right">
                <div
                  className={`text-[15px] font-bold leading-tight ${
                    idx === 0
                      ? "text-emerald-600 dark:text-emerald-400"
                      : "text-slate-900 dark:text-slate-50"
                  }`}
                >
                  {formatUSD(row.expected_lift)}
                </div>
                <div className="text-[10px] text-slate-500 dark:text-slate-400 font-mono mt-0.5">
                  RAF +{(row.raf_coefficient || 0).toFixed(3)}
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}

      <div className="mt-3 pt-2.5 border-t border-slate-100 dark:border-slate-800 text-[10px] text-slate-500 dark:text-slate-400 leading-relaxed">
        Score = patients × coefficient × $12,000 PMPY × confidence · Peer bar
        shows avg capture rate among same-specialty providers.
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-[10px] p-4 shadow-sm">
      {children}
    </div>
  );
}

function Header({ totalLift }: { totalLift?: number }) {
  return (
    <div className="flex items-end justify-between mb-3.5">
      <div>
        <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-1">
          Top $ Opportunities
        </div>
        <div className="text-sm text-slate-500 dark:text-slate-400">
          What to code first
        </div>
      </div>
      {totalLift !== undefined && totalLift > 0 ? (
        <div className="px-2.5 py-1 rounded-full bg-emerald-50 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400 text-[11px] font-bold">
          {formatUSD(totalLift)} total
        </div>
      ) : null}
    </div>
  );
}

function PeerBar({ rate }: { rate: number | null | undefined }) {
  if (rate === null || rate === undefined) {
    return <span className="text-slate-500 dark:text-slate-400">peer n/a</span>;
  }
  const pct = Math.max(0, Math.min(1, rate));
  return (
    <span
      className="inline-flex items-center gap-1.5"
      title={`Peer capture rate: ${formatPct(rate)}`}
    >
      <span className="inline-block w-9 h-[5px] bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden relative">
        <span
          className="block h-full"
          style={{
            width: `${pct * 100}%`,
            background: pct >= 0.7 ? CHART.emerald500 : pct >= 0.4 ? CHART.blue600 : CHART.amber500,
          }}
        />
      </span>
      <span className="font-mono">{formatPct(rate)}</span>
    </span>
  );
}
