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
  type SpecialtyBenchmarks,
  type SpecialtyCohort,
  type SpecialtyCohortRow,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Tokens
// ---------------------------------------------------------------------------
const T = {
  emerald: "#10B981",
  emerald50: "#ECFDF5",
  blue: "#2563EB",
  blue50: "#EFF6FF",
  amber: "#F59E0B",
  amber50: "#FFFBEB",
  red: "#EF4444",
  red50: "#FEF2F2",
  slate100: "#F1F5F9",
  slate200: "#E2E8F0",
  slate300: "#CBD5E1",
  slate400: "#94A3B8",
  slate500: "#64748B",
  slate700: "#334155",
  slate900: "#0F172A",
  white: "#FFFFFF",
  primaryLight: "#EFF6FF",
};

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

function chipColor(percentile: number | null): { fg: string; bg: string } {
  if (percentile === null || percentile === undefined) {
    return { fg: T.slate400, bg: T.slate100 };
  }
  if (percentile >= 75) return { fg: T.emerald, bg: T.emerald50 };
  if (percentile >= 50) return { fg: T.blue, bg: T.blue50 };
  if (percentile >= 25) return { fg: T.amber, bg: T.amber50 };
  return { fg: T.red, bg: T.red50 };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export interface SpecialtyBenchmarkTabProps {
  /** The currently-focused provider — its row gets highlighted. */
  providerId: number;
  /** Specialty string used to find the cohort.  Required — pass from drawer. */
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
    queryFn: () => getSpecialtyBenchmarks(year),
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
      <div style={{ padding: 18, color: T.slate500, fontSize: 13 }}>
        Loading specialty benchmarks…
      </div>
    );
  }

  if (q.isError) {
    return (
      <div style={{ padding: 18, color: T.red, fontSize: 13 }}>
        Specialty benchmarks unavailable. {(q.error as Error)?.message ?? ""}
      </div>
    );
  }

  if (!cohort) {
    return (
      <div style={{ padding: 18, color: T.slate500, fontSize: 13 }}>
        No cohort data for{" "}
        <strong style={{ color: T.slate700 }}>{specialty ?? "this specialty"}</strong>.
      </div>
    );
  }

  if (cohort.insufficient_peers) {
    return (
      <div style={{ padding: 18, fontSize: 13 }}>
        <div style={{ fontWeight: 600, color: T.slate900, marginBottom: 4 }}>
          {cohort.specialty}
        </div>
        <div style={{ color: T.slate500 }}>
          Cohort has only {cohort.cohort_size} provider{cohort.cohort_size === 1 ? "" : "s"} —
          peer benchmarking requires ≥3 providers in the same specialty.
        </div>
      </div>
    );
  }

  const peerCount = Math.max(0, cohort.cohort_size - 1);

  return (
    <div style={{ padding: 18 }}>
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: 12,
        }}
      >
        <div>
          <div
            style={{
              fontSize: 10,
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.06em",
              color: T.slate400,
            }}
          >
            Specialty Cohort
          </div>
          <div style={{ fontSize: 16, fontWeight: 700, color: T.slate900 }}>
            {cohort.specialty}
          </div>
        </div>
        <div style={{ fontSize: 12, color: T.slate500 }}>
          {cohort.cohort_size} providers · {peerCount} peers
        </div>
      </div>

      {/* Cohort summary strip */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: `repeat(${COLUMNS.length}, minmax(0, 1fr))`,
          gap: 8,
          padding: "10px 12px",
          background: T.slate100,
          borderRadius: 8,
          marginBottom: 14,
        }}
      >
        {COLUMNS.map((c) => {
          const stat = cohort.cohort_summary[c.key];
          return (
            <div key={c.key}>
              <div
                style={{
                  fontSize: 9,
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.04em",
                  color: T.slate400,
                  marginBottom: 4,
                }}
              >
                {c.label}
              </div>
              <div style={{ fontSize: 11, color: T.slate700 }}>
                <div>med {fmt(stat?.median, c.format)}</div>
                <div style={{ color: T.slate400, fontSize: 10 }}>
                  {fmt(stat?.min, c.format)} – {fmt(stat?.max, c.format)}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Provider table */}
      <div
        style={{
          border: `1px solid ${T.slate200}`,
          borderRadius: 8,
          overflow: "auto",
        }}
      >
        <table
          style={{
            width: "100%",
            borderCollapse: "collapse",
            fontSize: 12,
          }}
        >
          <thead>
            <tr style={{ background: T.slate100 }}>
              <th
                style={{
                  textAlign: "left",
                  padding: "8px 12px",
                  color: T.slate500,
                  fontWeight: 600,
                  textTransform: "uppercase",
                  fontSize: 10,
                  letterSpacing: "0.04em",
                  borderBottom: `1px solid ${T.slate200}`,
                }}
              >
                Provider
              </th>
              {COLUMNS.map((c) => (
                <th
                  key={c.key}
                  style={{
                    textAlign: "left",
                    padding: "8px 8px",
                    color: T.slate500,
                    fontWeight: 600,
                    textTransform: "uppercase",
                    fontSize: 10,
                    letterSpacing: "0.04em",
                    borderBottom: `1px solid ${T.slate200}`,
                    whiteSpace: "nowrap",
                  }}
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

      <div
        style={{
          marginTop: 10,
          fontSize: 10,
          color: T.slate400,
          lineHeight: 1.5,
        }}
      >
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
  const name = row.full_name?.trim() || `${row.first_name} ${row.last_name}`.trim();
  return (
    <tr
      style={{
        background: isCurrent ? T.primaryLight : T.white,
        borderBottom: `1px solid ${T.slate100}`,
      }}
    >
      <td
        style={{
          padding: "10px 12px",
          color: isCurrent ? T.blue : T.slate900,
          fontWeight: isCurrent ? 700 : 600,
          whiteSpace: "nowrap",
        }}
      >
        {name || `Provider ${row.provider_id}`}
        {isCurrent && (
          <span
            style={{
              marginLeft: 6,
              fontSize: 9,
              fontWeight: 700,
              color: T.blue,
              background: T.blue50,
              padding: "2px 6px",
              borderRadius: 999,
              textTransform: "uppercase",
              letterSpacing: "0.04em",
            }}
          >
            You
          </span>
        )}
      </td>
      {COLUMNS.map((c) => {
        const value = row.kpis[c.key];
        const pct = row.percentiles[c.key];
        const { fg, bg } = chipColor(pct);
        return (
          <td key={c.key} style={{ padding: "10px 8px", whiteSpace: "nowrap" }}>
            <div
              title={
                pct !== null && pct !== undefined
                  ? `${c.label}: ${Math.round(pct)}th percentile`
                  : `${c.label}: no peer data`
              }
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "3px 8px",
                background: bg,
                color: fg,
                borderRadius: 999,
                fontWeight: 700,
                fontSize: 11,
              }}
            >
              <span>{fmt(value, c.format)}</span>
              {pct !== null && pct !== undefined && (
                <span
                  style={{
                    fontSize: 9,
                    opacity: 0.85,
                    fontWeight: 600,
                  }}
                >
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
