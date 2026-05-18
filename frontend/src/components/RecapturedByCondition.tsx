"use client";

/**
 * Side-by-side horizontal bar chart of top conditions:
 * left = $ recaptured, right = $ at risk.  Pulls from the CFO summary.
 */

import React from "react";
import { useQuery } from "@tanstack/react-query";

import { getCfoSummary, type CfoExecutiveSummary } from "@/lib/api";

const T = {
  white: "#FFFFFF",
  slate900: "#0F172A",
  slate700: "#334155",
  slate500: "#64748B",
  slate300: "#CBD5E1",
  slate200: "#E2E8F0",
  slate100: "#F1F5F9",
  slate50: "#F8FAFC",
  emerald500: "#10B981",
  red500: "#EF4444",
};

function formatUSD(n: number): string {
  if (!Number.isFinite(n)) return "$0";
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(1)}k`;
  return `$${Math.round(n).toLocaleString()}`;
}

interface BarProps {
  label: string;
  sub: string;
  amount: number;
  max: number;
  color: string;
  align: "left" | "right";
}

function Bar({ label, sub, amount, max, color, align }: BarProps) {
  const pct = max > 0 ? (amount / max) * 100 : 0;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: 12,
          color: T.slate700,
        }}
      >
        <span style={{ fontWeight: 600 }}>{label}</span>
        <span style={{ fontVariantNumeric: "tabular-nums", color: T.slate500 }}>{sub}</span>
      </div>
      <div
        style={{
          background: T.slate100,
          borderRadius: 6,
          height: 10,
          overflow: "hidden",
          display: "flex",
          flexDirection: align === "right" ? "row-reverse" : "row",
        }}
      >
        <div
          style={{
            width: `${Math.max(2, pct)}%`,
            background: color,
            height: "100%",
            transition: "width 0.4s ease",
          }}
        />
      </div>
      <div
        style={{
          fontSize: 12,
          fontWeight: 700,
          color: T.slate900,
          textAlign: align === "right" ? "right" : "left",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {formatUSD(amount)}
      </div>
    </div>
  );
}

interface Props {
  year?: number;
}

export default function RecapturedByCondition({ year }: Props) {
  const yr = year ?? new Date().getFullYear();
  const { data, isLoading, isError } = useQuery<CfoExecutiveSummary>({
    queryKey: ["cfo-summary", yr],
    queryFn: () => getCfoSummary(yr),
  });

  if (isLoading) {
    return (
      <div
        style={{
          background: T.white,
          border: `1px solid ${T.slate200}`,
          borderRadius: 10,
          padding: 16,
          height: 220,
        }}
      />
    );
  }
  if (isError || !data) return null;

  const recap = data.top_3_recaptured_conditions;
  const risk = data.top_3_at_risk_conditions;
  const maxRecap = Math.max(1, ...recap.map((c) => c.dollars));
  const maxRisk = Math.max(1, ...risk.map((c) => c.dollars));

  return (
    <div
      style={{
        background: T.white,
        border: `1px solid ${T.slate200}`,
        borderRadius: 10,
        padding: 16,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 12,
          fontSize: 13,
          fontWeight: 600,
          color: T.slate700,
        }}
      >
        <span>Recaptured by condition (top 3)</span>
        <span style={{ color: T.slate500 }}>vs $ at risk</span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ fontSize: 11, color: T.emerald500, fontWeight: 700, textTransform: "uppercase" }}>
            $ Recaptured
          </div>
          {recap.length === 0 ? (
            <div style={{ fontSize: 12, color: T.slate500 }}>No closures yet this year.</div>
          ) : (
            recap.map((c) => (
              <Bar
                key={`recap-${c.hcc_code}`}
                label={c.description}
                sub={`HCC ${c.hcc_code} · ${c.count}`}
                amount={c.dollars}
                max={maxRecap}
                color={T.emerald500}
                align="left"
              />
            ))
          )}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div
            style={{
              fontSize: 11,
              color: T.red500,
              fontWeight: 700,
              textTransform: "uppercase",
              textAlign: "right",
            }}
          >
            $ At Risk
          </div>
          {risk.length === 0 ? (
            <div style={{ fontSize: 12, color: T.slate500, textAlign: "right" }}>
              No open gaps.
            </div>
          ) : (
            risk.map((c) => (
              <Bar
                key={`risk-${c.hcc_code}`}
                label={c.description}
                sub={`HCC ${c.hcc_code} · ${c.count}`}
                amount={c.dollars}
                max={maxRisk}
                color={T.red500}
                align="right"
              />
            ))
          )}
        </div>
      </div>
    </div>
  );
}
