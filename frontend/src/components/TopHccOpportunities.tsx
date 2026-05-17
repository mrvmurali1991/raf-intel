"use client";

/**
 * Top $ HCC Opportunities card.
 *
 * Surfaces the top 5 HCCs that are NOT yet coded in this provider's panel,
 * ranked by expected $ revenue lift. Backed by
 * GET /api/providers/{id}/top-opportunities.
 *
 * Design language matches RAFForecastCard (inline-styled tokens, slate /
 * blue / emerald / amber palette) so it slots into the provider detail
 * drawer without conflicting with the existing `premium-card` styling.
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

const T = {
  white: "#FFFFFF",
  slate900: "#0F172A",
  slate700: "#334155",
  slate500: "#64748B",
  slate400: "#64748B",
  slate300: "#CBD5E1",
  slate200: "#E2E8F0",
  slate100: "#F1F5F9",
  emerald600: "#059669",
  emerald500: "#10B981",
  emerald50: "#ECFDF5",
  amber600: "#D97706",
  amber500: "#F59E0B",
  amber50: "#FFFBEB",
  red500: "#EF4444",
  red50: "#FEF2F2",
  blue600: "#2563EB",
  blue50: "#EFF6FF",
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
        <div style={{ color: T.slate500, fontSize: 13 }}>
          Calculating top opportunities…
        </div>
      </Card>
    );
  }

  if (q.isError || !q.data) {
    return (
      <Card>
        <Header />
        <div style={{ color: T.red500, fontSize: 13 }}>
          Top opportunities unavailable. {(q.error as Error)?.message ?? ""}
        </div>
      </Card>
    );
  }

  const items = q.data.opportunities ?? [];
  const totalLift = items.reduce((s, r) => s + (r.expected_lift || 0), 0);

  return (
    <Card>
      <Header totalLift={totalLift} />

      {items.length === 0 ? (
        <div
          style={{
            fontSize: 12,
            color: T.slate500,
            fontStyle: "italic",
            paddingTop: 8,
          }}
        >
          No coding opportunities surfaced. Run a suspect scan to populate this
          list.
        </div>
      ) : (
        <ol
          style={{
            listStyle: "none",
            padding: 0,
            margin: 0,
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          {items.map((row, idx) => (
            <li
              key={row.hcc_code}
              style={{
                display: "grid",
                gridTemplateColumns: "auto 1fr auto",
                gap: 12,
                alignItems: "center",
                padding: "10px 12px",
                background: idx === 0 ? T.emerald50 : T.slate100,
                borderRadius: 8,
                border: `1px solid ${idx === 0 ? T.emerald500 : T.slate200}`,
              }}
            >
              {/* HCC chip */}
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  minWidth: 48,
                  padding: "3px 8px",
                  background: T.white,
                  border: `1px solid ${T.slate300}`,
                  borderRadius: 6,
                  fontSize: 11,
                  fontWeight: 700,
                  color: T.slate900,
                  fontFamily: "monospace",
                }}
                title={`HCC ${row.hcc_code}`}
              >
                HCC {row.hcc_code}
              </div>

              {/* Label + meta */}
              <div style={{ minWidth: 0 }}>
                <div
                  style={{
                    fontSize: 13,
                    fontWeight: 600,
                    color: T.slate900,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                  title={row.hcc_label}
                >
                  {row.hcc_label}
                </div>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    marginTop: 2,
                    fontSize: 11,
                    color: T.slate500,
                  }}
                >
                  <span>
                    {row.patient_count_missing}{" "}
                    {row.patient_count_missing === 1 ? "patient" : "patients"}
                  </span>
                  <span style={{ color: T.slate300 }}>·</span>
                  <span>conf {formatPct(row.avg_confidence)}</span>
                  <span style={{ color: T.slate300 }}>·</span>
                  <PeerBar rate={row.peer_capture_rate} />
                </div>
              </div>

              {/* $ lift right-aligned */}
              <div style={{ textAlign: "right" }}>
                <div
                  style={{
                    fontSize: 15,
                    fontWeight: 700,
                    color: idx === 0 ? T.emerald600 : T.slate900,
                    lineHeight: 1.1,
                  }}
                >
                  {formatUSD(row.expected_lift)}
                </div>
                <div
                  style={{
                    fontSize: 10,
                    color: T.slate400,
                    fontFamily: "monospace",
                    marginTop: 2,
                  }}
                >
                  RAF +{(row.raf_coefficient || 0).toFixed(3)}
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}

      <div
        style={{
          marginTop: 12,
          paddingTop: 10,
          borderTop: `1px solid ${T.slate100}`,
          fontSize: 10,
          color: T.slate400,
          lineHeight: 1.5,
        }}
      >
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
    <div
      style={{
        background: T.white,
        border: `1px solid ${T.slate200}`,
        borderRadius: 12,
        padding: 16,
        boxShadow: "0 1px 2px rgba(15, 23, 42, 0.04)",
      }}
    >
      {children}
    </div>
  );
}

function Header({ totalLift }: { totalLift?: number }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-end",
        justifyContent: "space-between",
        marginBottom: 14,
      }}
    >
      <div>
        <div
          style={{
            fontSize: 10,
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            color: T.slate400,
            marginBottom: 4,
          }}
        >
          Top $ Opportunities
        </div>
        <div style={{ fontSize: 13, color: T.slate500 }}>
          What to code first
        </div>
      </div>
      {totalLift !== undefined && totalLift > 0 ? (
        <div
          style={{
            padding: "4px 10px",
            borderRadius: 999,
            background: T.emerald50,
            color: T.emerald600,
            fontSize: 11,
            fontWeight: 700,
          }}
        >
          {formatUSD(totalLift)} total
        </div>
      ) : null}
    </div>
  );
}

function PeerBar({ rate }: { rate: number | null | undefined }) {
  if (rate === null || rate === undefined) {
    return <span style={{ color: T.slate400 }}>peer n/a</span>;
  }
  const pct = Math.max(0, Math.min(1, rate));
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
      }}
      title={`Peer capture rate: ${formatPct(rate)}`}
    >
      <span
        style={{
          display: "inline-block",
          width: 36,
          height: 5,
          background: T.slate200,
          borderRadius: 999,
          overflow: "hidden",
          position: "relative",
        }}
      >
        <span
          style={{
            display: "block",
            width: `${pct * 100}%`,
            height: "100%",
            background: pct >= 0.7 ? T.emerald500 : pct >= 0.4 ? T.blue600 : T.amber500,
          }}
        />
      </span>
      <span style={{ fontFamily: "monospace" }}>{formatPct(rate)}</span>
    </span>
  );
}
