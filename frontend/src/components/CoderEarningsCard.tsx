"use client";

/**
 * CoderEarningsCard — per-coder summary card.
 *
 * Shows year-to-date earnings, bonus-at-risk, and a 12-month sparkline.
 * Designed for the recapture page sidebar when a coder is signed in.
 */

import React from "react";
import { useQuery } from "@tanstack/react-query";
import { DollarSign, AlertCircle, Calendar, TrendingUp } from "lucide-react";

import { getCoderEarnings, type CoderEarnings } from "@/lib/api";

const MONTH_INITIALS = ["", "J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];

export interface CoderEarningsCardProps {
  coderId: number;
  coderName?: string;
  year?: number;
}

function formatCurrency(n: number): string {
  return "$" + Math.round(n).toLocaleString("en-US");
}

export function CoderEarningsCard({ coderId, coderName, year }: CoderEarningsCardProps) {
  const { data, isLoading, isError } = useQuery<CoderEarnings>({
    queryKey: ["coder-earnings", coderId, year ?? "current"],
    queryFn: () => getCoderEarnings(coderId, year),
    staleTime: 60_000,
    enabled: Number.isFinite(coderId) && coderId > 0,
  });

  if (isLoading) {
    return (
      <div className="premium-card shimmer" style={{ height: 220, borderRadius: 12 }} />
    );
  }
  if (isError || !data) {
    return null; // graceful degradation
  }

  const maxBonus = Math.max(1, ...data.monthly_breakdown.map((m) => m.bonus));

  return (
    <div className="premium-card" style={{ padding: 24 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "#94A3B8" }}>
            Your Bonus · {data.year}
          </div>
          <div style={{ fontSize: 16, fontWeight: 700, color: "#0F172A", marginTop: 2 }}>
            {coderName || data.name}
          </div>
        </div>
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            padding: "4px 10px",
            borderRadius: 999,
            background: "#EFF6FF",
            color: "#1D4ED8",
            fontSize: 11,
            fontWeight: 700,
          }}
        >
          <Calendar size={12} aria-hidden />
          {data.current_multiplier.toFixed(2)}× now
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginBottom: 16 }}>
        <Stat
          label="Earned"
          value={formatCurrency(data.bonus_earned)}
          accent="#059669"
          icon={<DollarSign size={14} />}
        />
        <Stat
          label="At Risk"
          value={formatCurrency(data.bonus_at_risk)}
          accent="#DC2626"
          icon={<AlertCircle size={14} />}
          sub={`${data.open_gaps} open`}
        />
        <Stat
          label="Closures"
          value={String(data.ytd_closures)}
          accent="#2563EB"
          icon={<TrendingUp size={14} />}
        />
      </div>

      {/* 12-month sparkline */}
      <div>
        <div style={{ fontSize: 11, fontWeight: 600, color: "#64748B", marginBottom: 6 }}>
          Monthly bonus trend
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(12, 1fr)",
            gap: 4,
            alignItems: "end",
            height: 72,
          }}
        >
          {data.monthly_breakdown.map((m) => {
            const heightPct = m.bonus > 0 ? Math.max(8, (m.bonus / maxBonus) * 100) : 4;
            const isCurrent = m.month === data.current_month;
            return (
              <div key={m.month} style={{ display: "flex", flexDirection: "column", alignItems: "center", height: "100%", justifyContent: "flex-end" }}>
                <div
                  title={`${MONTH_INITIALS[m.month]} · ${m.closures} closures · ${formatCurrency(m.bonus)}`}
                  style={{
                    width: "100%",
                    height: `${heightPct}%`,
                    background: isCurrent
                      ? "linear-gradient(180deg, #1D4ED8, #2563EB)"
                      : m.bonus > 0
                      ? "linear-gradient(180deg, #93C5FD, #60A5FA)"
                      : "#E2E8F0",
                    borderRadius: 3,
                    transition: "height 0.4s ease",
                  }}
                />
              </div>
            );
          })}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(12, 1fr)", gap: 4, marginTop: 4 }}>
          {data.monthly_breakdown.map((m) => (
            <div
              key={m.month}
              style={{
                fontSize: 10,
                color: m.month === data.current_month ? "#1D4ED8" : "#94A3B8",
                fontWeight: m.month === data.current_month ? 700 : 500,
                textAlign: "center",
              }}
            >
              {MONTH_INITIALS[m.month]}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  accent,
  icon,
  sub,
}: {
  label: string;
  value: string;
  accent: string;
  icon: React.ReactNode;
  sub?: string;
}) {
  return (
    <div
      style={{
        padding: "10px 12px",
        borderRadius: 10,
        background: "#F8FAFC",
        border: "1px solid #E2E8F0",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: "#64748B", fontWeight: 600 }}>
        <span style={{ color: accent }}>{icon}</span>
        {label}
      </div>
      <div className="tabular-nums" style={{ fontSize: 18, fontWeight: 700, color: "#0F172A", marginTop: 2 }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 10, color: "#94A3B8", marginTop: 1 }}>{sub}</div>
      )}
    </div>
  );
}

export default CoderEarningsCard;
