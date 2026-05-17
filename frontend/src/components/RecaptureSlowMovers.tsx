"use client";

/**
 * RecaptureSlowMovers
 * --------------------
 * Compact "campaign target" list — the 10 HCC codes whose gaps take the
 * longest to close, ranked by avg days. Each row exposes the count of open
 * gaps, the $ at risk, and an "Assign to campaign" CTA that currently
 * console.logs (a future PR will hook into the campaign service).
 */

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Clock } from "lucide-react";

import {
  getRecaptureSlowMovers,
  type RecaptureSlowMoversResponse,
} from "@/lib/api";

function fmtCurrency(n: number): string {
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${Math.round(n).toLocaleString()}`;
}

export interface RecaptureSlowMoversProps {
  year?: number;
  limit?: number;
}

export default function RecaptureSlowMovers({ year, limit = 10 }: RecaptureSlowMoversProps) {
  const { data, isLoading, isError } = useQuery<RecaptureSlowMoversResponse>({
    queryKey: ["recapture-slow-movers", year, limit],
    queryFn: () => getRecaptureSlowMovers(year, limit),
  });

  if (isLoading) {
    return (
      <div
        style={{
          height: 320,
          borderRadius: 12,
          background: "linear-gradient(90deg, #F1F5F9 0%, #E2E8F0 50%, #F1F5F9 100%)",
          backgroundSize: "200% 100%",
          animation: "shimmer 1.5s infinite",
          marginBottom: 24,
        }}
      />
    );
  }
  if (isError || !data) {
    return (
      <div
        style={{
          padding: 14,
          borderRadius: 10,
          background: "#FEF2F2",
          border: "1px solid #FECACA",
          color: "#B91C1C",
          fontSize: 13,
          marginBottom: 24,
        }}
      >
        Failed to load slow-movers.
      </div>
    );
  }

  const rows = data.slow_movers ?? [];

  return (
    <div
      className="premium-card"
      style={{ padding: 24, marginBottom: 24, background: "#fff", borderRadius: 12 }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <div>
          <h3 className="gradient-text" style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>
            Slowest HCCs to Close
          </h3>
          <p style={{ margin: "4px 0 0", fontSize: 12, color: "#64748B" }}>
            Top {data.limit} HCC codes by avg days-to-close · campaign candidates
          </p>
        </div>
        <span
          style={{
            fontSize: 11,
            color: "#64748B",
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.06em",
          }}
        >
          {data.year}
        </span>
      </div>

      {rows.length === 0 ? (
        <div style={{ padding: 16, textAlign: "center", color: "#64748B", fontSize: 13 }}>
          No slow-movers in this cohort.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {rows.map((r, idx) => (
            <SlowMoverRow key={`${r.hcc_code}-${idx}`} idx={idx} row={r} />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// SlowMoverRow
// ---------------------------------------------------------------------------

interface RowProps {
  idx: number;
  row: RecaptureSlowMoversResponse["slow_movers"][number];
}

function SlowMoverRow({ idx, row }: RowProps) {
  const handleAssign = React.useCallback(() => {
    // TODO: wire into campaign service in a follow-up PR.
    // eslint-disable-next-line no-console
    console.log("[campaign] assign HCC", row.hcc_code, {
      avg_days: row.avg_days_to_close,
      open: row.open_count,
      at_risk: row.$_at_risk,
    });
  }, [row]);

  const days = row.avg_days_to_close;
  const daysLabel = days === null ? "No closures" : `${days.toFixed(0)} d avg`;
  const daysColour = days === null ? "#DC2626" : days > 90 ? "#DC2626" : days > 45 ? "#F59E0B" : "#10B981";

  return (
    <div
      className="hover-lift"
      style={{
        display: "grid",
        gridTemplateColumns: "32px 64px 1fr 92px 92px 130px",
        gap: 12,
        alignItems: "center",
        padding: "10px 12px",
        background: idx % 2 === 0 ? "#F8FAFC" : "transparent",
        borderRadius: 8,
        fontSize: 13,
      }}
    >
      <span
        style={{
          fontSize: 11,
          fontWeight: 700,
          color: "#64748B",
          textAlign: "center",
        }}
      >
        {idx + 1}
      </span>
      <span
        className="tabular-nums"
        style={{
          fontFamily: "monospace",
          fontSize: 12,
          fontWeight: 600,
          color: "#2563EB",
        }}
      >
        HCC {row.hcc_code}
      </span>
      <span
        style={{
          fontWeight: 500,
          color: "#0F172A",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
        title={row.description}
      >
        {row.description}
      </span>
      <span
        className="tabular-nums"
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          color: daysColour,
          fontWeight: 600,
          fontSize: 12,
        }}
      >
        <Clock size={12} />
        {daysLabel}
      </span>
      <span
        className="tabular-nums"
        style={{ color: "#0F172A", fontWeight: 600, textAlign: "right" }}
      >
        {row.open_count} open · {fmtCurrency(row.$_at_risk)}
      </span>
      <button
        onClick={handleAssign}
        className="btn-press"
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 4,
          padding: "6px 10px",
          borderRadius: 6,
          border: "1px solid #E2E8F0",
          background: "#fff",
          color: "#2563EB",
          fontSize: 12,
          fontWeight: 600,
          cursor: "pointer",
          transition: "all 0.15s ease",
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = "#EFF6FF";
          e.currentTarget.style.borderColor = "#2563EB";
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = "#fff";
          e.currentTarget.style.borderColor = "#E2E8F0";
        }}
      >
        Assign to campaign
        <ArrowUpRight size={12} />
      </button>
    </div>
  );
}
