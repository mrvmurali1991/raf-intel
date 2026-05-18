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
import { Users, Award, ArrowUpDown, ArrowUp, ArrowDown, RefreshCw } from "lucide-react";

import api from "@/lib/api";
import { PageHeader, EmptyState } from "@/components/healthcare-ui";
import { tokens } from "@/styles/tokens";

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

async function fetchProviderScorecards(year: number): Promise<ProviderScorecardListResponse> {
  const { data } = await api.get<ProviderScorecardListResponse>(
    `/api/provider-scorecards?year=${year}`,
  );
  return data;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDelta(delta: number, decimals = 1, suffix = ""): string {
  const sign = delta > 0 ? "+" : "";
  return `${sign}${delta.toFixed(decimals)}${suffix}`;
}

/**
 * For RAF higher is better, but only marginally — peer comparison is still
 * relevant for outliers. For recapture % and MEAT % higher is unambiguously
 * better.  All three metrics use the same direction here (higher = better).
 */
function deltaColor(delta: number, epsilon = 0.05): string {
  if (delta > epsilon) return tokens.successStrong;
  if (delta < -epsilon) return tokens.dangerStrong;
  return tokens.slate500;
}

function DeltaBadge({ delta, suffix = "", decimals = 1, epsilon = 0.05 }: {
  delta: number;
  suffix?: string;
  decimals?: number;
  epsilon?: number;
}) {
  const color = deltaColor(delta, epsilon);
  return (
    <span
      style={{
        marginLeft: 6,
        fontSize: 11,
        fontWeight: 600,
        color,
        whiteSpace: "nowrap",
      }}
      title="vs tenant average"
    >
      {formatDelta(delta, decimals, suffix)}
    </span>
  );
}

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
      style={{
        padding: "12px 14px",
        textAlign: align,
        fontSize: 11,
        fontWeight: 600,
        color: tokens.slate600,
        textTransform: "uppercase",
        letterSpacing: 0.4,
        cursor: "pointer",
        userSelect: "none",
        borderBottom: `1px solid ${tokens.slate200}`,
        background: tokens.slate50,
      }}
    >
      <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
        {label}
        {active ? (
          direction === "asc" ? <ArrowUp size={12} /> : <ArrowDown size={12} />
        ) : (
          <ArrowUpDown size={12} style={{ opacity: 0.4 }} />
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
    <div style={{ background: tokens.white, border: `1px solid ${tokens.slate200}`, borderRadius: 10, overflow: "hidden" }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            {["Provider", "Panel", "Avg RAF", "Recapture %", "MEAT %"].map((h) => (
              <th key={h} style={{ padding: "12px 14px", fontSize: 11, fontWeight: 600, color: tokens.slate600, textTransform: "uppercase", background: tokens.slate50, borderBottom: `1px solid ${tokens.slate200}`, textAlign: h === "Provider" ? "left" : "right" }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((_, i) => (
            <tr key={i}>
              {Array.from({ length: 5 }).map((__, j) => (
                <td key={j} style={{ padding: "14px", borderBottom: `1px solid ${tokens.slate100}` }}>
                  <div
                    style={{
                      height: 12,
                      width: j === 0 ? "70%" : "50%",
                      marginLeft: j === 0 ? 0 : "auto",
                      background: tokens.slate100,
                      borderRadius: 4,
                      animation: "pulse 1.4s ease-in-out infinite",
                    }}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <style jsx>{`
        @keyframes pulse {
          0%, 100% { opacity: 0.5; }
          50% { opacity: 1; }
        }
      `}</style>
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
        return sortDir === "asc"
          ? va.localeCompare(vb)
          : vb.localeCompare(va);
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

  // Year options: current + previous 3
  const yearOptions = useMemo(
    () => [currentYear, currentYear - 1, currentYear - 2, currentYear - 3],
    [currentYear],
  );

  return (
    <div style={{ maxWidth: 1280, margin: "0 auto", padding: "24px 28px" }}>
      <PageHeader
        title="Provider Scorecards"
        subtitle="Per-provider performance with peer benchmarks vs the tenant average"
        icon={<Award size={20} />}
        actions={
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <label style={{ fontSize: 12, color: tokens.slate600, display: "flex", alignItems: "center", gap: 6 }}>
              Year
              <select
                value={year}
                onChange={(e) => setYear(Number(e.target.value))}
                style={{
                  padding: "6px 10px",
                  borderRadius: 8,
                  border: `1px solid ${tokens.slate200}`,
                  fontSize: 13,
                  background: tokens.white,
                  color: tokens.slate900,
                }}
              >
                {yearOptions.map((y) => (
                  <option key={y} value={y}>{y}</option>
                ))}
              </select>
            </label>
            <button
              onClick={() => refetch()}
              disabled={isFetching}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "7px 12px",
                borderRadius: 8,
                border: `1px solid ${tokens.slate200}`,
                background: tokens.white,
                color: tokens.slate700,
                fontSize: 13,
                cursor: isFetching ? "wait" : "pointer",
              }}
            >
              <RefreshCw size={14} style={{ animation: isFetching ? "spin 1s linear infinite" : "none" }} />
              Refresh
            </button>
          </div>
        }
      />

      {/* Tenant averages summary strip */}
      {data && !isLoading && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
            gap: 12,
            marginBottom: 20,
          }}
        >
          {[
            { label: "Tenant Avg RAF", value: data.tenant_avg_raf.toFixed(3) },
            { label: "Tenant Avg Recapture %", value: `${data.tenant_avg_recapture_rate.toFixed(1)}%` },
            { label: "Tenant Avg MEAT %", value: data.tenant_avg_meat_compliance === null ? "—" : `${data.tenant_avg_meat_compliance.toFixed(1)}%` },
          ].map((kpi) => (
            <div
              key={kpi.label}
              style={{
                background: tokens.white,
                border: `1px solid ${tokens.slate200}`,
                borderRadius: 10,
                padding: "14px 16px",
              }}
            >
              <div style={{ fontSize: 11, color: tokens.slate600, textTransform: "uppercase", letterSpacing: 0.3, fontWeight: 600 }}>
                {kpi.label}
              </div>
              <div style={{ marginTop: 4, fontSize: 20, fontWeight: 700, color: tokens.slate900 }}>
                {kpi.value}
              </div>
            </div>
          ))}
        </div>
      )}

      {isLoading && <TableSkeleton />}

      {isError && (
        <EmptyState
          title="Could not load provider scorecards"
          description="The backend returned an error. Try again, or pick a different year."
        />
      )}

      {!isLoading && !isError && sortedRows.length === 0 && (
        <EmptyState
          icon={<Users size={28} />}
          title="No providers found"
          description={`No active providers have data for ${year}. Try a different year or seed provider attribution.`}
        />
      )}

      {!isLoading && !isError && sortedRows.length > 0 && (
        <div
          style={{
            background: tokens.white,
            border: `1px solid ${tokens.slate200}`,
            borderRadius: 10,
            overflow: "hidden",
          }}
        >
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <SortHeader label="Provider" active={sortKey === "provider_name"} direction={sortDir} onClick={() => handleSort("provider_name")} />
                <SortHeader label="Panel" active={sortKey === "panel_size"} direction={sortDir} onClick={() => handleSort("panel_size")} align="right" />
                <SortHeader label="Avg RAF" active={sortKey === "avg_raf"} direction={sortDir} onClick={() => handleSort("avg_raf")} align="right" />
                <SortHeader label="Recapture %" active={sortKey === "recapture_rate_pct"} direction={sortDir} onClick={() => handleSort("recapture_rate_pct")} align="right" />
                <SortHeader label="MEAT %" active={sortKey === "meat_compliance_pct"} direction={sortDir} onClick={() => handleSort("meat_compliance_pct")} align="right" />
              </tr>
            </thead>
            <tbody>
              {sortedRows.map((r, idx) => {
                const rafDelta = r.avg_raf - r.tenant_avg_raf;
                const recDelta = r.recapture_rate_pct - r.tenant_avg_recapture_rate;
                const meatDelta =
                  r.meat_compliance_pct !== null && r.tenant_avg_meat_compliance !== null
                    ? r.meat_compliance_pct - r.tenant_avg_meat_compliance
                    : null;
                const recTooltip =
                  r.data_quality_flag === "leakage_exceeds_prior_hcc_count"
                    ? "Open gaps exceed prior-year HCC count — leakage > 100% (likely cohort expansion mid-year)"
                    : undefined;
                const stripe = idx % 2 === 0 ? tokens.white : tokens.slate50;
                return (
                  <tr key={r.provider_id} style={{ background: stripe }}>
                    <td style={{ padding: "12px 14px", borderBottom: `1px solid ${tokens.slate100}` }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: tokens.slate900 }}>
                        {r.provider_name || `Provider #${r.provider_id}`}
                      </div>
                      {(r.specialty || r.provider_npi) && (
                        <div style={{ marginTop: 2, fontSize: 11, color: tokens.slate500 }}>
                          {r.specialty || "—"}{r.provider_npi ? `  ·  NPI ${r.provider_npi}` : ""}
                        </div>
                      )}
                    </td>
                    <td style={{ padding: "12px 14px", textAlign: "right", fontSize: 13, color: tokens.slate900, borderBottom: `1px solid ${tokens.slate100}` }}>
                      {r.panel_size.toLocaleString()}
                    </td>
                    <td style={{ padding: "12px 14px", textAlign: "right", fontSize: 13, color: tokens.slate900, borderBottom: `1px solid ${tokens.slate100}` }}>
                      <span style={{ fontWeight: 600 }}>{r.avg_raf.toFixed(3)}</span>
                      <DeltaBadge delta={rafDelta} decimals={3} epsilon={0.01} />
                    </td>
                    <td
                      style={{ padding: "12px 14px", textAlign: "right", fontSize: 13, color: tokens.slate900, borderBottom: `1px solid ${tokens.slate100}` }}
                      title={recTooltip}
                    >
                      {r.data_quality_flag === "leakage_exceeds_prior_hcc_count" ? (
                        <span style={{ fontWeight: 600, color: tokens.slate400 }} aria-label="Metric not yet computed — data quality anomaly">—</span>
                      ) : (
                        <>
                          <span style={{ fontWeight: 600 }}>{r.recapture_rate_pct.toFixed(1)}%</span>
                          <DeltaBadge delta={recDelta} decimals={1} suffix="pp" epsilon={0.1} />
                        </>
                      )}
                    </td>
                    <td style={{ padding: "12px 14px", textAlign: "right", fontSize: 13, color: tokens.slate900, borderBottom: `1px solid ${tokens.slate100}` }}>
                      {r.meat_compliance_pct === null ? (
                        <span style={{ fontWeight: 600, color: tokens.slate400 }} title="No HCCs MEAT-scored yet for this provider's panel">—</span>
                      ) : (
                        <>
                          <span style={{ fontWeight: 600 }}>{r.meat_compliance_pct.toFixed(1)}%</span>
                          {meatDelta !== null && (
                            <DeltaBadge delta={meatDelta} decimals={1} suffix="pp" epsilon={0.1} />
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
      )}

      <style jsx>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
