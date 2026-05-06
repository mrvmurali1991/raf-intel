"use client";

/**
 * PeerPercentileRibbon
 *
 * A compact horizontal strip showing how a provider ranks against their
 * specialty cohort across six KPIs.  Each KPI gets a mini-bar whose height
 * is proportional to the percentile (0-100); colour encodes performance:
 *
 *   ≥75 emerald, ≥50 blue, ≥25 amber, <25 red.
 *
 * If the cohort has fewer than 3 peers, the API returns
 * `insufficient_peers: true` and we render nothing — peer comparison is
 * meaningless at that scale.
 *
 * Renders inline-styled tokens so it stays Tailwind-free, matching the rest
 * of the providers page palette.
 */
import React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  getPeerPercentile,
  type PeerKpiKey,
  type PeerPercentile,
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
};

// ---------------------------------------------------------------------------
// KPI metadata — display order, label, cohort-context noun
// ---------------------------------------------------------------------------
type KpiMeta = {
  key: PeerKpiKey;
  short: string;     // 3-char token under bar
  label: string;     // tooltip phrase ("MEAT compliance")
};

const KPI_ORDER: KpiMeta[] = [
  { key: "average_raf",                 short: "RAF", label: "Average RAF" },
  { key: "hcc_capture_rate",            short: "CAP", label: "HCC capture" },
  { key: "recapture_rate",              short: "RCP", label: "Recapture" },
  { key: "meat_completeness_avg",       short: "MET", label: "MEAT compliance" },
  { key: "revenue_opportunity",         short: "REV", label: "Revenue opportunity" },
  { key: "documentation_quality_score", short: "DOC", label: "Doc quality" },
];

function colorFor(percentile: number | null): { fg: string; bg: string } {
  if (percentile === null || percentile === undefined) {
    return { fg: T.slate400, bg: T.slate100 };
  }
  if (percentile >= 75) return { fg: T.emerald, bg: T.emerald50 };
  if (percentile >= 50) return { fg: T.blue, bg: T.blue50 };
  if (percentile >= 25) return { fg: T.amber, bg: T.amber50 };
  return { fg: T.red, bg: T.red50 };
}

function ordinal(p: number): string {
  const r = Math.round(p);
  const v = r % 100;
  if (v >= 11 && v <= 13) return `${r}th`;
  switch (r % 10) {
    case 1: return `${r}st`;
    case 2: return `${r}nd`;
    case 3: return `${r}rd`;
    default: return `${r}th`;
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export interface PeerPercentileRibbonProps {
  providerId: number | string;
  /** Defaults to current year on the backend if omitted. */
  year?: number;
  /** Optional cohort noun shown in tooltip ("PCPs", "specialists"). Falls back to "peers". */
  cohortNoun?: string;
  /** Compact mode — slightly shorter bars (default true on table rows). */
  compact?: boolean;
}

export default function PeerPercentileRibbon({
  providerId,
  year,
  cohortNoun = "peers",
  compact = false,
}: PeerPercentileRibbonProps) {
  const q = useQuery<PeerPercentile>({
    queryKey: ["peer-percentile", providerId, year],
    queryFn: () => getPeerPercentile(providerId, year),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: 1,
  });

  // Skeleton — render an empty strip so layout doesn't reflow.
  if (q.isLoading) {
    return <Skeleton compact={compact} />;
  }

  if (q.isError || !q.data) {
    return null;
  }

  // Graceful fallback: small / unknown cohort → render nothing per spec.
  if (q.data.insufficient_peers || q.data.cohort_size < 3) {
    return null;
  }

  const peerCount = Math.max(0, q.data.cohort_size - 1);
  const data = q.data;

  const barH = compact ? 22 : 28;
  const barW = compact ? 14 : 18;
  const gap = compact ? 4 : 6;

  return (
    <div
      role="group"
      aria-label="Peer percentile ribbon"
      style={{
        display: "inline-flex",
        alignItems: "flex-end",
        gap,
        padding: "4px 8px",
        background: T.white,
        border: `1px solid ${T.slate200}`,
        borderRadius: 8,
        boxShadow: "0 1px 1px rgba(15, 23, 42, 0.03)",
      }}
    >
      {KPI_ORDER.map((kpi) => {
        const pct = data.percentiles[kpi.key] ?? null;
        const { fg, bg } = colorFor(pct);
        const fillH = pct === null ? 4 : Math.max(4, Math.round((pct / 100) * barH));
        const tooltip =
          pct === null
            ? `${kpi.label}: no data`
            : `${kpi.label}: ${ordinal(pct)} percentile vs ${peerCount} ${cohortNoun} in ${data.specialty ?? "your cohort"}`;

        return (
          <div
            key={kpi.key}
            title={tooltip}
            aria-label={tooltip}
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 3,
            }}
          >
            <div
              style={{
                width: barW,
                height: barH,
                background: bg,
                borderRadius: 4,
                position: "relative",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  position: "absolute",
                  bottom: 0,
                  left: 0,
                  right: 0,
                  height: fillH,
                  background: fg,
                  borderRadius: 4,
                  transition: "height 0.25s ease",
                }}
              />
            </div>
            <div
              style={{
                fontSize: 8,
                fontWeight: 700,
                color: T.slate500,
                letterSpacing: "0.04em",
                lineHeight: 1,
              }}
            >
              {kpi.short}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Loading skeleton — same footprint, gray bars
// ---------------------------------------------------------------------------
function Skeleton({ compact }: { compact: boolean }) {
  const barH = compact ? 22 : 28;
  const barW = compact ? 14 : 18;
  const gap = compact ? 4 : 6;
  return (
    <div
      aria-hidden
      style={{
        display: "inline-flex",
        alignItems: "flex-end",
        gap,
        padding: "4px 8px",
        background: T.white,
        border: `1px solid ${T.slate200}`,
        borderRadius: 8,
        opacity: 0.6,
      }}
    >
      {KPI_ORDER.map((k) => (
        <div
          key={k.key}
          style={{
            width: barW,
            height: barH,
            background: T.slate100,
            borderRadius: 4,
          }}
        />
      ))}
    </div>
  );
}
