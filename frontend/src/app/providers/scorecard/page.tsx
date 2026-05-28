"use client";

/**
 * Provider Scorecards v2 — peer-benchmarked sortable table.
 *
 * Pareto / Inovalon-style scorecard:
 *   columns = Provider | Panel | Avg RAF | Recapture % | MEAT %
 *   each metric cell shows the value AND a +/- delta vs the tenant
 *   average for that metric (green when better than peer, red when
 *   worse).
 *
 * Backend: /api/provider-scorecards (mounted via provider_scorecards
 * router; v1 mount and the /api/v1/... mount both serve this page).
 */

import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Users,
  Award,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  RefreshCw,
} from "lucide-react";

import api from "@/lib/api";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState } from "@/components/ui/empty-state";

// ---------------------------------------------------------------------------
// Types — mirror backend ProviderScorecardV2
// ---------------------------------------------------------------------------

interface ProviderScorecardV2 {
  provider_id: number;
  provider_npi: string | null;
  provider_name: string;
  specialty: string | null;
  panel_size: number;
  avg_raf: number;
  recapture_rate_pct: number;
  // null when no HCCs have been MEAT-scored yet — render em-dash.
  meat_compliance_pct: number | null;
  meat_coverage_pct: number | null;
  // Set when computed leakage > 1 (data-quality anomaly).
  data_quality_flag: string | null;
  tenant_avg_raf: number;
  tenant_avg_recapture_rate: number;
  tenant_avg_meat_compliance: number | null;
  year: number;
}

interface ProviderScorecardListResponse {
  year: number;
  providers: ProviderScorecardV2[];
  tenant_avg_raf: number;
  tenant_avg_recapture_rate: number;
  tenant_avg_meat_compliance: number | null;
}

type SortKey =
  | "provider_name"
  | "panel_size"
  | "avg_raf"
  | "recapture_rate_pct"
  | "meat_compliance_pct";

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

async function fetchProviderScorecards(
  year: number,
): Promise<ProviderScorecardListResponse> {
  const { data } = await api.get<ProviderScorecardListResponse>(
    `/api/provider-scorecards?year=${year}`,
  );
  return data;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDelta(
  delta: number,
  decimals = 1,
  suffix = "",
): string {
  const sign = delta > 0 ? "+" : "";
  return `${sign}${delta.toFixed(decimals)}${suffix}`;
}

function deltaColorClass(delta: number, epsilon = 0.05): string {
  if (delta > epsilon) return "text-emerald-600 dark:text-emerald-400";
  if (delta < -epsilon) return "text-red-600 dark:text-red-400";
  return "text-muted-foreground";
}

function DeltaBadge({
  delta,
  suffix = "",
  decimals = 1,
  epsilon = 0.05,
}: {
  delta: number;
  suffix?: string;
  decimals?: number;
  epsilon?: number;
}) {
  return (
    <span
      className={`ml-1.5 text-[11px] font-semibold whitespace-nowrap ${deltaColorClass(delta, epsilon)}`}
      title="vs tenant average"
    >
      {formatDelta(delta, decimals, suffix)}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Sort header
// ---------------------------------------------------------------------------

function SortHeader({
  label,
  active,
  direction,
  onClick,
  align = "left",
}: {
  label: string;
  active: boolean;
  direction: "asc" | "desc";
  onClick: () => void;
  align?: "left" | "right";
}) {
  return (
    <th
      onClick={onClick}
      className={`px-3.5 py-3 text-[11px] font-semibold uppercase tracking-wide cursor-pointer select-none border-b border-border bg-muted/40 text-muted-foreground hover:text-foreground transition-colors ${align === "right" ? "text-right" : "text-left"}`}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {active ? (
          direction === "asc" ? (
            <ArrowUp size={12} />
          ) : (
            <ArrowDown size={12} />
          )
        ) : (
          <ArrowUpDown size={12} className="opacity-40" />
        )}
      </span>
    </th>
  );
}

// ---------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------

function TableSkeleton() {
  const rows = Array.from({ length: 6 });
  return (
    <div
      className="bg-card border border-border rounded-xl overflow-hidden"
      aria-busy="true"
      aria-label="Loading scorecards"
    >
      <table className="w-full border-collapse">
        <thead>
          <tr>
            {["Provider", "Panel", "Avg RAF", "Recapture %", "MEAT %"].map(
              (h) => (
                <th
                  key={h}
                  className={`px-3.5 py-3 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground bg-muted/40 border-b border-border ${h === "Provider" ? "text-left" : "text-right"}`}
                >
                  {h}
                </th>
              ),
            )}
          </tr>
        </thead>
        <tbody>
          {rows.map((_, i) => (
            <tr key={i}>
              {Array.from({ length: 5 }).map((__, j) => (
                <td key={j} className="px-3.5 py-3.5 border-b border-border/50">
                  <div
                    className={`h-3 rounded animate-pulse bg-muted ${j === 0 ? "w-[70%]" : "w-1/2 ml-auto"}`}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tenant benchmark strip
// ---------------------------------------------------------------------------

function BenchmarkStrip({
  data,
}: {
  data: ProviderScorecardListResponse;
}) {
  const items = [
    { label: "Tenant Avg RAF", value: data.tenant_avg_raf.toFixed(3) },
    {
      label: "Tenant Avg Recapture",
      value: `${data.tenant_avg_recapture_rate.toFixed(1)}%`,
    },
    {
      label: "Tenant Avg MEAT",
      value:
        data.tenant_avg_meat_compliance === null
          ? "—"
          : `${data.tenant_avg_meat_compliance.toFixed(1)}%`,
    },
  ];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-5">
      {items.map((kpi) => (
        <div
          key={kpi.label}
          className="bg-card border border-border rounded-xl px-4 py-3.5"
        >
          <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            {kpi.label}
          </div>
          <div className="mt-1 text-xl font-bold text-foreground">
            {kpi.value}
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ProviderScorecardsPage() {
  const currentYear = new Date().getFullYear();
  const [year, setYear] = useState<number>(currentYear);
  const [sortKey, setSortKey] = useState<SortKey>("recapture_rate_pct");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ["provider-scorecards-v2", year],
    queryFn: () => fetchProviderScorecards(year),
    staleTime: 60_000,
  });

  const sortedRows = useMemo(() => {
    if (!data?.providers) return [];
    const rows = [...data.providers];
    rows.sort((a, b) => {
      const va = a[sortKey];
      const vb = b[sortKey];
      if (typeof va === "string" && typeof vb === "string") {
        return sortDir === "asc" ? va.localeCompare(vb) : vb.localeCompare(va);
      }
      const na = Number(va);
      const nb = Number(vb);
      return sortDir === "asc" ? na - nb : nb - na;
    });
    return rows;
  }, [data, sortKey, sortDir]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "provider_name" ? "asc" : "desc");
    }
  };

  const yearOptions = useMemo(
    () => [currentYear, currentYear - 1, currentYear - 2, currentYear - 3],
    [currentYear],
  );

  return (
    <div className="p-6 max-w-screen-xl mx-auto">
      <PageHeader
        title="Provider Scorecards"
        subtitle="Per-provider performance with peer benchmarks vs the tenant average"
        icon={<Award size={20} />}
        actions={
          <div className="flex items-center gap-2.5">
            <label className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
              Year
              <select
                value={year}
                onChange={(e) => setYear(Number(e.target.value))}
                className="px-2.5 py-1.5 rounded-lg border border-border bg-card text-[13px] text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              >
                {yearOptions.map((y) => (
                  <option key={y} value={y}>
                    {y}
                  </option>
                ))}
              </select>
            </label>
            <button
              onClick={() => refetch()}
              disabled={isFetching}
              aria-label="Refresh provider scorecards"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border bg-card text-[13px] text-foreground hover:bg-muted/60 disabled:opacity-50 disabled:cursor-wait transition-colors"
            >
              <RefreshCw
                size={14}
                className={isFetching ? "animate-spin" : ""}
                aria-hidden
              />
              Refresh
            </button>
          </div>
        }
      />

      {/* Tenant averages summary strip */}
      {data && !isLoading && <BenchmarkStrip data={data} />}

      {/* Loading skeleton */}
      {isLoading && <TableSkeleton />}

      {/* Error state */}
      {isError && (
        <EmptyState
          state="no-data"
          icon={<Award size={28} />}
          title="Could not load provider scorecards"
          description="The backend returned an error. Try again or pick a different year."
          cta={{ label: "Retry", onClick: () => refetch() }}
        />
      )}

      {/* No providers */}
      {!isLoading && !isError && sortedRows.length === 0 && (
        <EmptyState
          state="no-data"
          icon={<Users size={28} />}
          title="No providers found"
          description={`No active providers have data for ${year}. Try a different year or seed provider attribution.`}
        />
      )}

      {/* Table */}
      {!isLoading && !isError && sortedRows.length > 0 && (
        <div className="bg-card border border-border rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-[13px]">
              <thead>
                <tr>
                  <SortHeader
                    label="Provider"
                    active={sortKey === "provider_name"}
                    direction={sortDir}
                    onClick={() => handleSort("provider_name")}
                  />
                  <SortHeader
                    label="Panel"
                    active={sortKey === "panel_size"}
                    direction={sortDir}
                    onClick={() => handleSort("panel_size")}
                    align="right"
                  />
                  <SortHeader
                    label="Avg RAF"
                    active={sortKey === "avg_raf"}
                    direction={sortDir}
                    onClick={() => handleSort("avg_raf")}
                    align="right"
                  />
                  <SortHeader
                    label="Recapture %"
                    active={sortKey === "recapture_rate_pct"}
                    direction={sortDir}
                    onClick={() => handleSort("recapture_rate_pct")}
                    align="right"
                  />
                  <SortHeader
                    label="MEAT %"
                    active={sortKey === "meat_compliance_pct"}
                    direction={sortDir}
                    onClick={() => handleSort("meat_compliance_pct")}
                    align="right"
                  />
                </tr>
              </thead>
              <tbody>
                {sortedRows.map((r, idx) => {
                  const rafDelta = r.avg_raf - r.tenant_avg_raf;
                  const recDelta =
                    r.recapture_rate_pct - r.tenant_avg_recapture_rate;
                  const meatDelta =
                    r.meat_compliance_pct !== null &&
                    r.tenant_avg_meat_compliance !== null
                      ? r.meat_compliance_pct - r.tenant_avg_meat_compliance
                      : null;
                  const recTooltip =
                    r.data_quality_flag ===
                    "leakage_exceeds_prior_hcc_count"
                      ? "Open gaps exceed prior-year HCC count — leakage > 100% (likely cohort expansion mid-year)"
                      : undefined;
                  const stripeClass =
                    idx % 2 === 0 ? "bg-card" : "bg-muted/20";

                  return (
                    <tr
                      key={r.provider_id}
                      className={`${stripeClass} hover:bg-primary/5 transition-colors`}
                    >
                      {/* Provider */}
                      <td className="px-3.5 py-3 border-b border-border/50">
                        <div className="font-semibold text-foreground">
                          {r.provider_name || `Provider #${r.provider_id}`}
                        </div>
                        {(r.specialty || r.provider_npi) && (
                          <div className="mt-0.5 text-[11px] text-muted-foreground">
                            {r.specialty || "—"}
                            {r.provider_npi
                              ? `  ·  NPI ${r.provider_npi}`
                              : ""}
                          </div>
                        )}
                      </td>

                      {/* Panel */}
                      <td className="px-3.5 py-3 text-right border-b border-border/50 text-foreground">
                        {r.panel_size.toLocaleString()}
                      </td>

                      {/* Avg RAF */}
                      <td className="px-3.5 py-3 text-right border-b border-border/50">
                        <span className="font-semibold text-foreground">
                          {r.avg_raf.toFixed(3)}
                        </span>
                        <DeltaBadge
                          delta={rafDelta}
                          decimals={3}
                          epsilon={0.01}
                        />
                      </td>

                      {/* Recapture % */}
                      <td
                        className="px-3.5 py-3 text-right border-b border-border/50"
                        title={recTooltip}
                      >
                        {r.data_quality_flag ===
                        "leakage_exceeds_prior_hcc_count" ? (
                          <span
                            className="font-semibold text-muted-foreground"
                            aria-label="Metric not yet computed — data quality anomaly"
                          >
                            —
                          </span>
                        ) : (
                          <>
                            <span className="font-semibold text-foreground">
                              {r.recapture_rate_pct.toFixed(1)}%
                            </span>
                            <DeltaBadge
                              delta={recDelta}
                              decimals={1}
                              suffix="pp"
                              epsilon={0.1}
                            />
                          </>
                        )}
                      </td>

                      {/* MEAT % */}
                      <td className="px-3.5 py-3 text-right border-b border-border/50">
                        {r.meat_compliance_pct === null ? (
                          <span
                            className="font-semibold text-muted-foreground"
                            title="No HCCs MEAT-scored yet for this provider's panel"
                          >
                            —
                          </span>
                        ) : (
                          <>
                            <span className="font-semibold text-foreground">
                              {r.meat_compliance_pct.toFixed(1)}%
                            </span>
                            {meatDelta !== null && (
                              <DeltaBadge
                                delta={meatDelta}
                                decimals={1}
                                suffix="pp"
                                epsilon={0.1}
                              />
                            )}
                          </>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Footer row count */}
          <div className="px-4 py-2.5 border-t border-border text-[12px] text-muted-foreground">
            {sortedRows.length} provider
            {sortedRows.length !== 1 ? "s" : ""} for {year}
          </div>
        </div>
      )}
    </div>
  );
}
