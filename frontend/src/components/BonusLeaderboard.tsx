"use client";

/**
 * BonusLeaderboard — ranked coder list with podium-style 1/2/3 highlighting.
 *
 * Columns: rank · name · closures · $ recaptured · bonus earned · pace bar.
 *
 * "Pace to target" is computed locally as ``ytd_closures / topPerformerClosures``
 * because we don't track per-user goals. This keeps the bar meaningful even
 * when goals are unknown — the leader is always 100%, and everyone else is
 * relative to the leader.
 */

import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Trophy, Medal, Award, TrendingUp } from "lucide-react";

import {
  getRecaptureBonusLeaderboard,
  type BonusLeaderboardResponse,
  type LeaderboardEntry,
} from "@/lib/api";

export interface BonusLeaderboardProps {
  year?: number;
  limit?: number;
  /** Highlight a specific coder (e.g. the signed-in user). */
  highlightCoderId?: number | null;
}

const PODIUM = {
  1: { bg: "linear-gradient(135deg, #FEF3C7, #FDE68A)", border: "#F59E0B", icon: <Trophy size={16} color="#B45309" />, label: "1st" },
  2: { bg: "linear-gradient(135deg, #F1F5F9, #E2E8F0)", border: "#94A3B8", icon: <Medal size={16} color="#475569" />, label: "2nd" },
  3: { bg: "linear-gradient(135deg, #FEF2F2, #FEE2E2)", border: "#F87171", icon: <Award size={16} color="#B91C1C" />, label: "3rd" },
} as const;

function formatCurrency(n: number): string {
  return "$" + Math.round(n).toLocaleString("en-US");
}

export function BonusLeaderboard({
  year,
  limit = 20,
  highlightCoderId,
}: BonusLeaderboardProps) {
  const { data, isLoading, isError } = useQuery<BonusLeaderboardResponse>({
    queryKey: ["recapture-bonus-leaderboard", year ?? "current", limit],
    queryFn: () => getRecaptureBonusLeaderboard(year, limit),
    staleTime: 60_000,
  });

  if (isLoading) {
    return (
      <div
        className="premium-card shimmer"
        style={{ height: 240, borderRadius: 12 }}
        aria-label="Loading leaderboard"
      />
    );
  }
  if (isError || !data) {
    return (
      <div
        className="premium-card"
        style={{ padding: 24, color: "#B91C1C", fontSize: 13 }}
      >
        Could not load the bonus leaderboard. Please refresh to retry.
      </div>
    );
  }

  const board = data.leaderboard;
  const topCount = board[0]?.ytd_closures || 1;

  return (
    <div className="premium-card" style={{ padding: 24 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <h3 className="gradient-text" style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>
          Bonus Leaderboard · {data.year}
        </h3>
        <div style={{ fontSize: 12, color: "#64748B", display: "flex", alignItems: "center", gap: 6 }}>
          <TrendingUp size={14} />
          Current month{" "}
          <span className="tabular-nums" style={{ fontWeight: 700 }}>
            {data.current_month_multiplier.multiplier.toFixed(2)}×
          </span>
        </div>
      </div>

      {board.length === 0 ? (
        <p style={{ margin: 0, color: "#64748B", fontSize: 13 }}>
          No coder closures yet for {data.year}. Bonuses will appear here as gaps
          are closed.
        </p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <Th>#</Th>
                <Th>Coder</Th>
                <Th align="right">Closures</Th>
                <Th align="right">$ Recaptured</Th>
                <Th align="right">Bonus Earned</Th>
                <Th>Pace to Leader</Th>
              </tr>
            </thead>
            <tbody>
              {board.map((row) => (
                <LeaderboardRow
                  key={row.rank}
                  row={row}
                  topCount={topCount}
                  highlight={
                    highlightCoderId !== undefined &&
                    highlightCoderId !== null &&
                    row.coder_id === highlightCoderId
                  }
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function LeaderboardRow({
  row,
  topCount,
  highlight,
}: {
  row: LeaderboardEntry;
  topCount: number;
  highlight: boolean;
}) {
  const podium = PODIUM[row.rank as 1 | 2 | 3];
  const pacePct = Math.min(100, Math.round((row.ytd_closures / Math.max(1, topCount)) * 100));

  return (
    <tr
      style={{
        background: highlight ? "rgba(37,99,235,0.06)" : "transparent",
        borderLeft: highlight ? "3px solid #2563EB" : "3px solid transparent",
      }}
    >
      <Td>
        {podium ? (
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "3px 10px",
              borderRadius: 999,
              background: podium.bg,
              border: `1px solid ${podium.border}`,
              fontSize: 11,
              fontWeight: 700,
              color: "#1F2937",
            }}
            aria-label={`Rank ${row.rank}`}
          >
            {podium.icon}
            {podium.label}
          </span>
        ) : (
          <span className="tabular-nums" style={{ fontSize: 12, fontWeight: 600, color: "#64748B" }}>
            {row.rank}
          </span>
        )}
      </Td>
      <Td>
        <div style={{ fontSize: 13, fontWeight: 600, color: "#0F172A" }}>{row.name}</div>
        {row.email && row.email !== row.name && (
          <div style={{ fontSize: 11, color: "#94A3B8" }}>{row.email}</div>
        )}
      </Td>
      <Td align="right">
        <span className="tabular-nums" style={{ fontSize: 13, fontWeight: 600 }}>
          {row.ytd_closures.toLocaleString()}
        </span>
      </Td>
      <Td align="right">
        <span className="tabular-nums" style={{ fontSize: 13 }}>
          {formatCurrency(row.ytd_dollars_recaptured)}
        </span>
      </Td>
      <Td align="right">
        <span className="tabular-nums" style={{ fontSize: 13, fontWeight: 700, color: "#059669" }}>
          {formatCurrency(row.bonus_earned)}
        </span>
      </Td>
      <Td>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            minWidth: 140,
          }}
          aria-label={`${pacePct}% of leader`}
        >
          <div
            style={{
              flex: 1,
              height: 8,
              borderRadius: 4,
              background: "#E2E8F0",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                width: `${pacePct}%`,
                height: "100%",
                borderRadius: 4,
                background:
                  row.rank === 1
                    ? "linear-gradient(90deg, #F59E0B, #FBBF24)"
                    : "linear-gradient(90deg, #2563EB, #3B82F6)",
                transition: "width 0.6s ease",
              }}
            />
          </div>
          <span className="tabular-nums" style={{ fontSize: 11, color: "#64748B", width: 36, textAlign: "right" }}>
            {pacePct}%
          </span>
        </div>
      </Td>
    </tr>
  );
}

function Th({ children, align = "left" }: { children: React.ReactNode; align?: "left" | "right" }) {
  return (
    <th
      style={{
        padding: "10px 12px",
        fontSize: 11,
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.06em",
        color: "#94A3B8",
        textAlign: align,
        borderBottom: "2px solid #E2E8F0",
        background: "#F8FAFC",
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </th>
  );
}

function Td({ children, align = "left" }: { children: React.ReactNode; align?: "left" | "right" }) {
  return (
    <td
      style={{
        padding: "10px 12px",
        textAlign: align,
        borderBottom: "1px solid #F1F5F9",
        color: "#0F172A",
        verticalAlign: "middle",
      }}
    >
      {children}
    </td>
  );
}

export default BonusLeaderboard;
